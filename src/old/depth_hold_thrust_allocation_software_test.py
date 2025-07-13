import numpy as np

# Depth change shoudl be positive up
# All cases are represented as [depth change, pitch, roll, C_fw, C_sd, C_up, D_fw, D_sd, D_up]

cases = np.array([[1, 0, 0, 1, 1, 1, 0, 0, 1],
                  [1, 45, 0, 1, 1, 1, 1, 0, 1],
                  [1, 0, 45, 1, 1, 1, 0, -1, 1],
                  [1, 45, 45, 1, 1, 1, 0.4, -0.4, 0.4],
                  [1, -80, 0, 1, 1, 1, -0.9, 0, 0.1],
                  [1, 0, 160, 1, 1, 1, 0, -0.2, -0.8],
                  [1, 45, 0, 10, 5, 1, 0.1, 0, 0.9]])

def calculate_direction(depth_change, pitch, roll, C_fw, C_sd, C_up):
    # This vector represents desired direction in global coordinates
    b = np.array([0, 0, depth_change])

    cp, sp = np.cos(np.deg2rad(pitch)), np.sin(np.deg2rad(pitch))
    cr, sr = np.cos(np.deg2rad(roll)),    np.sin(np.deg2rad(roll))

    # In this matrix columns are equal to the vector form of which way each of the directions we can move take us
    # First column is forward, second is side, third is up
    A = np.array([
    [cp, sp*sr,    -sp*cr],
    [0,  cr,       sr],
    [sp, cp*(-sr), cp*cr]
    ])

    speed_coefficients = np.diag([
        C_fw,
        C_sd,
        C_up
    ])

    A = A @ speed_coefficients

    # Solve for direction vector "x"
    try:
        x = np.linalg.solve(A, b)
    except np.linalg.LinAlgError as e:
        print(f"Error solving linear system for depth hold thrust allocation: {e}, using least squares instead.")
        x, *_ = np.linalg.lstsq(A, b, rcond=None)

    return x

i = 1
for case in cases:
    R = calculate_direction(case[0], case[1], case[2], case[3], case[4], case[5])
    print(f"Case {i}")
    print(f"Desired: {np.array([case[6], case[7], case[8]])}")
    print(f"Result: {R}")
    print()

    i += 1
