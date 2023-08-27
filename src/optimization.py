from typing import Tuple

import cvxpy as cp
import numpy as np


def optimize_fuel(
    p_target: np.ndarray,
    g: float,
    m: float,
    p0: np.ndarray,
    v0: np.ndarray,
    K: int,
    h: float,
    F_max: float,
    alpha: float,
    gamma: float,
    **kwargs: dict,
) -> Tuple[np.ndarray, np.ndarray, float, cp.Problem]:
    """

    Minimize fuel consumption for a rocket to land on a target

    :param p_target: landing target in m
    :param g: gravitational acceleration in m/s^2
    :param m: mass in kg
    :param p0: position in m
    :param v0: velocity in m/s
    :param K: Number of discretization steps
    :param h: discretization step in s
    :param F_max: maximum thrust of engine in kg*m/s^2 (Newton)
    :param alpha: Glide path angle in radian
    :param gamma: converts fuel consumption to liters of fuel consumption
    :return: position, thrust, fuel consumption, problem
    """

    P_min = p_target[2]

    # Variables
    V = cp.Variable((K + 1, 3))  # velocity
    P = cp.Variable((K + 1, 3))  # position
    F = cp.Variable((K, 3))  # thrust

    # Constraints
    # Match initial position and initial velocity
    constraints = [
        V[0] == v0,
        P[0] == p0,
        P[:, 2] >= P_min,
        # P[:, 2] <= P_max,
        F[:, 2] >= 0,
        V[:, 2] <= 0,
    ]

    # Match final position and 0 velocity
    constraints += [
        V[K] == [0, 0, 0],
        P[K] == p_target,
    ]

    # Physics dynamics for velocity
    constraints += [V[1:, :2] == V[:-1, :2] + h * (F[:, :2] / m)]
    constraints += [V[1:, 2] == V[:-1, 2] + h * (F[:, 2] / m - g)]

    # Physics dynamics for position
    constraints += [P[1:] == P[:-1] + (h / 2) * (V[:-1] + V[1:])]

    # Maximum thrust constraint
    constraints += [cp.norm(F, 2, axis=1) <= F_max]

    fuel_consumption = gamma * cp.sum(cp.norm(F, axis=1))

    # Regularization
    height_regularization = cp.sum(cp.abs(P[:, 2] - P_min))
    xy_regularization = cp.sum(cp.abs(P[:, :2] - p_target[:2].reshape((1, -1))))
    glide_violation = cp.pos(np.tan(alpha) * cp.norm(P[:, :2], axis=1) - P[:, 2])
    glide_violation = cp.sum(glide_violation)
    gamma_height = 1
    gamma_xy = 1
    gamma_glide = 1000
    reg = (
        gamma_height * height_regularization
        + gamma_xy * xy_regularization
        + gamma_glide * glide_violation
    )

    problem = cp.Problem(cp.Minimize(fuel_consumption + reg), constraints)
    problem.solve(**kwargs)
    return P.value, F.value, fuel_consumption.value, problem
