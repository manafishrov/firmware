/* SPDX-License-Identifier: BSD-2-Clause */
/*
 * manafish-camerad - rpicam-vid's H.264 stream plus full-resolution photos.
 *
 * Streams exactly like rpicam-vid (it accepts the same options and uses the
 * same rpicam-apps classes). A client on the photo socket sends one line with
 * an absolute output path without extension, for example
 * "/home/pi/.local/share/manafish/photos/photo_1". The camera then switches
 * to the full-sensor still mode for one frame and straight back to video, so
 * the stream only freezes for that switch. Replies, one line each:
 *
 *   captured            the frame is in memory and the video is running again
 *   saved <jpeg path>   the JPEG and the RAW .dng next to it are on disk
 *   error <message>     nothing (more) will be saved
 *
 * Encoding the files happens on a background thread after the video resumes,
 * so it never adds to the freeze.
 */

#include <atomic>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <memory>
#include <mutex>
#include <optional>
#include <span>
#include <string>
#include <thread>
#include <vector>

#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include "core/rpicam_encoder.hpp"
#include "core/still_options.hpp"
#include "image/image.hpp"
#include "output/output.hpp"

using namespace std::placeholders;

static volatile std::sig_atomic_t quit_received = 0;
static void quit_handler(int)
{
	quit_received = 1;
}

// The client may have given up; never let a reply raise SIGPIPE.
static void reply(int fd, std::string const &line)
{
	std::string message = line + "\n";
	[[maybe_unused]] ssize_t sent = send(fd, message.data(), message.size(), MSG_NOSIGNAL);
}

struct PhotoRequest
{
	int fd;
	std::string base;
};

// Accepts photo requests on a Unix socket and hands at most one at a time to
// the camera loop, which checks for it between video frames.
class PhotoServer
{
public:
	explicit PhotoServer(std::string path) : path_(std::move(path))
	{
		sockaddr_un address = {};
		address.sun_family = AF_UNIX;
		if (path_.size() >= sizeof(address.sun_path))
			throw std::runtime_error("photo socket path is too long");
		std::strncpy(address.sun_path, path_.c_str(), sizeof(address.sun_path) - 1);

		listen_fd_ = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
		if (listen_fd_ < 0)
			throw std::runtime_error("failed to create photo socket");
		// A killed predecessor leaves its socket file behind.
		unlink(path_.c_str());
		if (bind(listen_fd_, reinterpret_cast<sockaddr *>(&address), sizeof(address)) < 0 ||
			listen(listen_fd_, 4) < 0)
		{
			close(listen_fd_);
			throw std::runtime_error("failed to listen on photo socket " + path_ + ": " + std::strerror(errno));
		}
		thread_ = std::thread(&PhotoServer::acceptLoop, this);
	}

	~PhotoServer()
	{
		shutdown(listen_fd_, SHUT_RDWR); // wakes accept()
		thread_.join();
		close(listen_fd_);
		unlink(path_.c_str());
		if (pending_)
			close(pending_->fd);
	}

	bool Pending() const
	{
		return has_pending_.load(std::memory_order_acquire);
	}

	std::optional<PhotoRequest> Take()
	{
		std::lock_guard<std::mutex> lock(mutex_);
		std::optional<PhotoRequest> request = std::move(pending_);
		pending_.reset();
		has_pending_.store(false, std::memory_order_release);
		return request;
	}

private:
	void acceptLoop()
	{
		while (true)
		{
			int fd = accept4(listen_fd_, nullptr, nullptr, SOCK_CLOEXEC);
			if (fd >= 0)
				handle(fd);
			else if (errno != EINTR && errno != ECONNABORTED)
				return;
		}
	}

	void handle(int fd)
	{
		// A client that never finishes its line must not block later requests.
		timeval timeout = { 2, 0 };
		setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
		std::string line;
		bool complete = false;
		char c;
		while (line.size() < 4096 && read(fd, &c, 1) == 1)
		{
			if (c == '\n')
			{
				complete = true;
				break;
			}
			line += c;
		}
		if (!complete || line.empty() || line[0] != '/')
		{
			reply(fd, "error invalid photo request");
			close(fd);
			return;
		}

		std::lock_guard<std::mutex> lock(mutex_);
		if (pending_)
		{
			reply(fd, "error a photo is already being taken");
			close(fd);
			return;
		}
		pending_ = PhotoRequest { fd, line };
		has_pending_.store(true, std::memory_order_release);
	}

	std::string path_;
	int listen_fd_ = -1;
	std::thread thread_;
	std::mutex mutex_;
	std::optional<PhotoRequest> pending_;
	std::atomic<bool> has_pending_ = false;
};

// A still frame copied out of the camera buffers, which are freed when the
// camera switches back to video.
struct CapturedPhoto
{
	std::vector<std::vector<uint8_t>> still;
	std::vector<std::vector<uint8_t>> raw;
	StreamInfo still_info;
	StreamInfo raw_info;
	libcamera::ControlList metadata;
};

static std::vector<std::vector<uint8_t>> copy_planes(RPiCamApp &app, libcamera::FrameBuffer *buffer)
{
	BufferReadSync sync(&app, buffer);
	std::vector<std::vector<uint8_t>> planes;
	for (std::span<uint8_t> const &span : sync.Get())
		planes.emplace_back(span.begin(), span.end());
	return planes;
}

static std::vector<std::span<uint8_t>> spans(std::vector<std::vector<uint8_t>> &planes)
{
	std::vector<std::span<uint8_t>> result;
	for (std::vector<uint8_t> &plane : planes)
		result.emplace_back(plane);
	return result;
}

// Encodes photos on a low-priority thread, one at a time, so the video keeps
// running smoothly while a 12 MP JPEG and DNG are written.
class PhotoSaver
{
public:
	PhotoSaver(std::string camera_model, int quality) : camera_model_(std::move(camera_model))
	{
		OptsInternal &opts = options_.Set();
		opts.quality = quality;
		opts.restart = 0;
		opts.exif = {};
		opts.thumb_width = 320;
		opts.thumb_height = 240;
		opts.thumb_quality = 70;
	}

	~PhotoSaver()
	{
		if (thread_.joinable())
			thread_.join();
	}

	bool Busy() const
	{
		return busy_.load();
	}

	void Start(CapturedPhoto photo, PhotoRequest request)
	{
		if (thread_.joinable())
			thread_.join();
		busy_ = true;
		thread_ = std::thread(
			[this, photo = std::move(photo), request = std::move(request)]() mutable
			{
				setpriority(PRIO_PROCESS, gettid(), 10);
				std::string jpeg = request.base + ".jpg";
				std::string dng = request.base + ".dng";
				try
				{
					// Write under temporary names so nobody sees half-written files.
					options_.Set().output = jpeg;
					jpeg_save(spans(photo.still), photo.still_info, photo.metadata, jpeg + ".part", camera_model_,
							  &options_);
					dng_save(spans(photo.raw), photo.raw_info, photo.metadata, dng + ".part", camera_model_,
							 &options_);
					if (std::rename((dng + ".part").c_str(), dng.c_str()) ||
						std::rename((jpeg + ".part").c_str(), jpeg.c_str()))
						throw std::runtime_error(std::string("failed to rename photo: ") + std::strerror(errno));
					reply(request.fd, "saved " + jpeg);
				}
				catch (std::exception const &e)
				{
					std::remove((jpeg + ".part").c_str());
					std::remove((dng + ".part").c_str());
					reply(request.fd, std::string("error ") + e.what());
				}
				close(request.fd);
				busy_ = false;
			});
	}

private:
	StillOptions options_;
	std::string camera_model_;
	std::thread thread_;
	std::atomic<bool> busy_ = false;
};

static unsigned int get_colourspace_flags(std::string const &codec)
{
	if (codec == "mjpeg" || codec == "yuv420")
		return RPiCamEncoder::FLAG_VIDEO_JPEG_COLOURSPACE;
	return RPiCamEncoder::FLAG_VIDEO_NONE;
}

static void start_video(RPiCamEncoder &app, unsigned int video_flags)
{
	app.ConfigureVideo(video_flags);
	app.StartEncoder();
	app.StartCamera();
}

static void stop_camera(RPiCamEncoder &app)
{
	app.StopCamera(); // stop the camera first; stop complains if the encoder is slow to close
	app.StopEncoder(); // returns once the encoder has finished every frame it was given
	app.Teardown();
}

// Takes the first frame in the still mode. The control algorithms keep their
// exposure and white balance across the mode switch (as rpicam-still relies
// on), so that frame already matches the live video.
static CapturedPhoto capture_still(RPiCamEncoder &app)
{
	OptsInternal &opts = app.GetOptions()->Set();
	OptsInternal const video = opts;
	libcamera::Size sensor =
		app.GetProperties().get(properties::PixelArraySize).value_or(libcamera::Size(4056, 3040));
	opts.width = sensor.width;
	opts.height = sensor.height;
	opts.mode = Mode(sensor.width, sensor.height, 12, true);
	// The video framerate would make mode selection prefer the faster binned mode.
	opts.framerate = std::nullopt;
	opts.denoise = "auto"; // high-quality denoise for stills

	std::optional<CapturedPhoto> photo;
	std::string error;
	try
	{
		app.ConfigureStill(RPiCamApp::FLAG_STILL_RAW);
		app.StartCamera();
		while (!photo)
		{
			RPiCamApp::Msg msg = app.Wait();
			if (msg.type == RPiCamApp::MsgType::Timeout)
				throw std::runtime_error("camera timed out in photo mode");
			if (msg.type == RPiCamApp::MsgType::Quit)
				throw std::runtime_error("camera is shutting down");
			CompletedRequestPtr &request = std::get<CompletedRequestPtr>(msg.payload);
			photo = CapturedPhoto {
				copy_planes(app, request->buffers[app.StillStream()]),
				copy_planes(app, request->buffers[app.RawStream()]),
				app.GetStreamInfo(app.StillStream()),
				app.GetStreamInfo(app.RawStream()),
				request->metadata,
			};
		}
	}
	catch (std::exception const &e)
	{
		error = e.what();
	}
	opts.width = video.width;
	opts.height = video.height;
	opts.mode = video.mode;
	opts.framerate = video.framerate;
	opts.denoise = video.denoise;
	app.StopCamera();
	app.Teardown();
	if (!photo)
		throw std::runtime_error(error);
	return std::move(*photo);
}

static void take_photo(RPiCamEncoder &app, PhotoRequest request, PhotoSaver &saver, unsigned int video_flags)
{
	if (saver.Busy())
	{
		reply(request.fd, "error the previous photo is still being saved");
		close(request.fd);
		return;
	}

	auto start = std::chrono::steady_clock::now();
	stop_camera(app);
	std::optional<CapturedPhoto> photo;
	std::string error;
	try
	{
		photo = capture_still(app);
	}
	catch (std::exception const &e)
	{
		error = e.what();
	}
	// Restart the video even when the photo failed; an exception from here
	// ends the process and go2rtc starts a fresh stream.
	start_video(app, video_flags);
	auto frozen = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start);
	LOG(1, "Photo capture paused the video for " << frozen.count() << " ms");

	if (!photo)
	{
		LOG_ERROR("ERROR: photo capture failed: " << error);
		reply(request.fd, "error " + error);
		close(request.fd);
		return;
	}
	reply(request.fd, "captured");
	saver.Start(std::move(*photo), std::move(request));
}

static void event_loop(RPiCamEncoder &app, std::string const &photo_socket, int photo_quality)
{
	VideoOptions const *options = app.GetOptions();
	std::unique_ptr<Output> output = std::unique_ptr<Output>(Output::Create(options));
	app.SetEncodeOutputReadyCallback(std::bind(&Output::OutputReady, output.get(), _1, _2, _3, _4));
	app.SetMetadataReadyCallback(std::bind(&Output::MetadataReady, output.get(), _1));
	unsigned int const video_flags = get_colourspace_flags(options->Get().codec);

	app.OpenCamera();
	start_video(app, video_flags);

	std::signal(SIGINT, quit_handler);
	// Raised when go2rtc closes the stream pipe.
	std::signal(SIGPIPE, quit_handler);

	PhotoSaver saver(app.CameraModel(), photo_quality);
	std::unique_ptr<PhotoServer> server;
	if (!photo_socket.empty())
		server = std::make_unique<PhotoServer>(photo_socket);

	while (true)
	{
		RPiCamEncoder::Msg msg = app.Wait();
		if (msg.type == RPiCamApp::MsgType::Timeout)
		{
			LOG_ERROR("ERROR: Device timeout detected, attempting a restart!!!");
			app.StopCamera();
			app.StartCamera();
			continue;
		}
		if (msg.type == RPiCamEncoder::MsgType::Quit || quit_received)
			break;
		if (msg.type != RPiCamEncoder::MsgType::RequestComplete)
			throw std::runtime_error("unrecognised message!");

		if (server && server->Pending())
		{
			// Return this frame to the camera before it stops.
			msg.payload = {};
			if (std::optional<PhotoRequest> request = server->Take())
				take_photo(app, std::move(*request), saver, video_flags);
			continue;
		}
		CompletedRequestPtr &completed_request = std::get<CompletedRequestPtr>(msg.payload);
		app.EncodeBuffer(completed_request, app.VideoStream());
	}
	server.reset();
	app.StopCamera();
	app.StopEncoder();
}

// Removes "--name value" from argv so the remaining options are exactly
// rpicam-vid's, and returns the value.
static std::optional<std::string> take_option(int &argc, char *argv[], std::string const &name)
{
	for (int i = 1; i + 1 < argc; i++)
	{
		if (name != argv[i])
			continue;
		std::string value = argv[i + 1];
		for (int j = i; j + 2 <= argc; j++)
			argv[j] = argv[j + 2];
		argc -= 2;
		return value;
	}
	return std::nullopt;
}

int main(int argc, char *argv[])
{
	try
	{
		std::string photo_socket = take_option(argc, argv, "--photo-socket").value_or("");
		int photo_quality = std::stoi(take_option(argc, argv, "--photo-quality").value_or("95"));
		RPiCamEncoder app;
		VideoOptions *options = app.GetOptions();
		if (options->Parse(argc, argv))
		{
			if (options->Get().verbose >= 2)
				options->Get().Print();
			event_loop(app, photo_socket, photo_quality);
		}
	}
	catch (std::exception const &e)
	{
		LOG_ERROR("ERROR: *** " << e.what() << " ***");
		return -1;
	}
	return 0;
}
