from setuptools import setup, Extension

setup(
    name="dshot",
    version="0.1",
    packages=['dshot'],
    ext_modules=[
        Extension(
            'dshot.dshot',
            sources=['dshot/dshot.c'],
            extra_compile_args=['-O2']
        )
    ]
)
