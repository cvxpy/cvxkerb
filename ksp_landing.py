import time

import cvxpy as cp
import krpc
import numpy as np
from krpc.services.spacecenter import ReferenceFrame, Vessel
from scipy.spatial.transform import Rotation as R

from src.optimization import optimize_fuel

landing_platform = np.array([159780.5, -1018.1, -578410.4])
origin = np.array([-0.0021359772614235606, -0.004701372718752435, 0.152749662369653])


def run() -> None:
    """
    The main function containing the MPC loop
    """

    conn = krpc.connect(name="Landing")
    vessel = conn.space_center.active_vessel
    print(f"the vessel's name is: {vessel.name}")

    ref_frame = get_reference_frame(conn, vessel)

    position = conn.add_stream(vessel.position, ref_frame)
    velocity = conn.add_stream(vessel.velocity, ref_frame)

    relative_frame = ref_frame.create_relative(
        ref_frame, rotation=R.from_euler("yz", [-90, -90], degrees=True).as_quat()
    )
    vessel.auto_pilot.reference_frame = relative_frame
    vessel.auto_pilot.target_pitch_and_heading(60, 0)

    launch_rocket(vessel)

    while True:

        time.sleep(0.1)

        p = np.array(position())
        v = np.array(velocity())
        max_thrust = vessel.max_thrust

        if vessel.situation.name == "landed":
            vessel.control.throttle = 0
            break

        # Update the glide angle
        alpha = np.arctan(p[2] * 1.05 / np.linalg.norm(p[:2]))

        try:
            P, F, _, problem = optimize_fuel(
                origin,
                9.81,
                vessel.mass,
                p,
                v,
                100,
                1,
                max_thrust,
                alpha,
                1,
                solver=cp.MOSEK,
            )
        except (cp.SolverError, AssertionError) as e:
            print(e)
            if v[2] > 0:
                vessel.control.throttle = 0
            continue

        if F is None:
            print("no solution found")
            vessel.control.throttle = 0
            continue
        else:
            target_F = F[0]
        thrust_level = np.linalg.norm(target_F) / max_thrust

        direction = target_F / np.linalg.norm(target_F)
        xy_len = np.linalg.norm(direction[[0, 1]])

        # pitch between -90 and 90
        target_pitch = np.arctan2(direction[2], xy_len) * 180 / np.pi

        # heading between 0 and 360
        target_heading = (np.arctan2(direction[1], direction[0]) * 180 / np.pi) % 360

        vessel.auto_pilot.target_pitch_and_heading(target_pitch, target_heading)
        vessel.auto_pilot.engage()

        if thrust_level < 0.01:
            thrust_level = 0
        vessel.control.throttle = thrust_level

        conn.drawing.clear()
        draw_trajectory(conn, P, ref_frame)
        draw_F(conn, target_F, ref_frame, vessel.reference_frame)
        draw_autopilot_direction(
            conn, vessel.auto_pilot.target_direction, relative_frame, vessel.reference_frame
        )

        print("thrust: ", round(thrust_level, 2))

    conn.close()


def draw_trajectory(conn: krpc.Client, P: np.ndarray, ref_frame: ReferenceFrame) -> None:
    """
    Draw the next 10 points of the trajectory
    """
    for i in range(1, P.shape[0]):
        p = P[i]
        p0 = P[i - 1]
        conn.drawing.add_line(p0, p, ref_frame)
        if i > 10:
            break


def draw_F(
    conn: krpc.Client,
    target_F: np.ndarray,
    ref_frame: ReferenceFrame,
    vessel_ref_frame: ReferenceFrame,
) -> None:
    """
    Draw the target force vector in blue
    """
    transformed_F = conn.space_center.transform_direction(target_F, ref_frame, vessel_ref_frame)
    line = conn.drawing.add_line([0, 0, 0], transformed_F, vessel_ref_frame)
    line.color = (0, 0, 1)


def draw_autopilot_direction(
    conn: krpc.Client,
    direction: np.ndarray,
    ref_frame: ReferenceFrame,
    vessel_ref_frame: ReferenceFrame,
) -> None:
    """
    Draw the autopilot direction in red
    """
    transformed_direction = conn.space_center.transform_direction(
        direction, ref_frame, vessel_ref_frame
    )
    line = conn.drawing.add_line([0, 0, 0], np.array(transformed_direction) * 100, vessel_ref_frame)
    line.color = (1, 0, 0)


def draw_coordinate_system(conn: krpc.Client, ref_frame: ReferenceFrame) -> None:
    """
    Draw the coordinate system of the reference frame
    """
    line = conn.drawing.add_line([0, 0, 0], [10, 0, 0], ref_frame)
    line.color = (1, 0, 0)
    line = conn.drawing.add_line([0, 0, 0], [0, 10, 0], ref_frame)
    line.color = (0, 1, 0)
    line = conn.drawing.add_line([0, 0, 0], [0, 0, 10], ref_frame)
    line.color = (0, 0, 1)


def launch_rocket(vessel: Vessel) -> None:
    """
    Launch the rocket on a hard-coded trajectory
    """
    vessel.auto_pilot.engage()
    vessel.control.throttle = 1
    vessel.control.activate_next_stage()
    time.sleep(2)
    vessel.auto_pilot.target_pitch_and_heading(60, 180)
    time.sleep(6)
    vessel.control.throttle = 0


def get_reference_frame(conn: krpc.Client, vessel: Vessel) -> ReferenceFrame:
    """
    Get the reference frame of the landing platform
    """

    z = landing_platform
    z = z / np.linalg.norm(z)
    x = np.array([1, 0, 0])
    y = np.cross(z, x)
    y = y / np.linalg.norm(y)
    x = np.cross(y, z)
    x = x / np.linalg.norm(x)
    q = R.from_matrix(np.array([x, y, z]).T).as_quat()
    ref_frame = conn.space_center.ReferenceFrame.create_relative(
        vessel.orbit.body.reference_frame, position=landing_platform, rotation=q
    )
    return ref_frame


if __name__ == "__main__":
    run()
