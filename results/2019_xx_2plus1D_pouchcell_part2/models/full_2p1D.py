import pybamm
import numpy as np
import sys


def solve_full_2p1(C_rate=1, t_eval=None, thermal=False, var_pts=None):

    sys.setrecursionlimit(10000)
    options = {
        "current collector": "potential pair",
        "dimensionality": 2,
    }

    if thermal is True:
        options.update({"thermal": "x-lumped"})

    model = pybamm.lithium_ion.DFN(options=options)

    param = model.default_parameter_values
    param.update({"C-rate": C_rate})

    # discharge timescale
    if t_eval is None:
        tau = param.evaluate(pybamm.standard_parameters_lithium_ion.tau_discharge)
        t_end = 900 / tau
        t_eval = np.linspace(0, t_end, 120)

    solver = pybamm.IDAKLUSolver(atol=1e-3, rtol=1e-3, root_tol=1e-3)
    # solver = pybamm.CasadiSolver(atol=1e-6, rtol=1e-6, root_tol=1e-6)

    sim = pybamm.Simulation(
        model, parameter_values=param, var_pts=var_pts, solver=solver
    )

    sim.solve(t_eval=t_eval)

    t = sim.solution.t
    y = sim.solution.y

    # get variables for plotting
    t = sim.solution.t
    y = sim.solution.y

    time = pybamm.ProcessedVariable(sim.built_model.variables["Time [h]"], t, y)(t)
    discharge_capacity = pybamm.ProcessedVariable(
        sim.built_model.variables["Discharge capacity [A.h]"], t, y
    )(t)
    terminal_voltage = pybamm.ProcessedVariable(
        sim.built_model.variables["Terminal voltage [V]"], t, y
    )(t)

    phi_s_n_dim = pybamm.ProcessedVariable(
        sim.built_model.variables["Negative current collector potential [V]"],
        t,
        y,
        mesh=sim.mesh,
    )
    phi_s_p_dim = pybamm.ProcessedVariable(
        sim.built_model.variables["Positive current collector potential [V]"],
        t,
        y,
        mesh=sim.mesh,
    )
    V_loc = pybamm.ProcessedVariable(
        sim.built_model.variables["Local voltage [V]"], t, y, mesh=sim.mesh
    )

    V = pybamm.ProcessedVariable(
        sim.built_model.variables["Terminal voltage [V]"], t, y
    )

    def phi_s_p_reduced(t, y, z):
        return phi_s_p_dim(t=t, y=y, z=z) - V(t)

    I_density = pybamm.ProcessedVariable(
        sim.built_model.variables["Current collector current density [A.m-2]"],
        t,
        y,
        mesh=sim.mesh,
    )

    def av_cc_density(t):
        I = I_density(t=t, y=np.linspace(0, 1.5, 100), z=np.linspace(0, 1, 100))
        I_av = np.mean(np.mean(I, axis=0), axis=0)
        return I_av

    T_av = pybamm.ProcessedVariable(
        sim.built_model.variables["X-averaged cell temperature [K]"],
        t,
        y,
        mesh=sim.mesh,
    )

    T_vol_av = pybamm.ProcessedVariable(
        sim.built_model.variables["Volume-averaged cell temperature [K]"],
        t,
        y,
        mesh=sim.mesh,
    )

    plotting_variables = {
        "Terminal voltage [V]": terminal_voltage,
        "Time [h]": time,
        "Negative current collector potential [V]": phi_s_n_dim,
        "Positive current collector potential [V]": phi_s_p_dim,
        "Reduced positive current collector potential [V]": phi_s_p_reduced,
        "Discharge capacity [A.h]": discharge_capacity,
        "Local voltage [V]": V_loc,
        "L_z": param.process_symbol(pybamm.geometric_parameters.L_z).evaluate(),
        "Local current density [A.m-2]": I_density,
        "Average local current density [A.m-2]": av_cc_density(t),
        "X-averaged cell temperature [K]": T_av,
    }

    if thermal:
        plotting_variables.update({"Volume-averaged cell temperature [K]": T_vol_av(t)})

    return plotting_variables
