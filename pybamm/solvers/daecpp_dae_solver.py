#
# Solver class using dae-cpp DAE solver
# (see `https://github.com/ikorotkin/dae-cpp`)
#
import pybamm
import pydae
import numpy as np
import scipy.sparse as sparse


class DaecppDaeSolver(pybamm.DaeSolver):
    """Solve a discretised model, using dae-cpp.

    Parameters
    ----------
    method : str, optional
        The method to use in solve_ivp (default is "BDF")
    tol : float, optional
        The tolerance for the solver (default is 1e-8). Set as the both reltol and
        abstol in solve_ivp.
    root_method : str, optional
        The method to use to find initial conditions (default is "lm")
    root_tol : float, optional
        The tolerance for the initial-condition solver (default is 1e-6).
    """

    def __init__(self, method="BDF", tol=1e-8, root_method="lm", root_tol=1e-6):
        # TODO: check if dae-cpp is installed

        super().__init__(method, tol, root_method, root_tol)

    def integrate(
        self, residuals, y0, t_eval, events=None, mass_matrix=None, jacobian=None
    ):
        """
        Solve a DAE model defined by residuals with initial conditions y0.

        Parameters
        ----------
        residuals : method
            A function that takes in t, y and ydot and returns the residuals of the
            equations
        y0 : numeric type
            The initial conditions
        t_eval : numeric type
            The times at which to compute the solution
        events : method, optional
            A function that takes in t and y and returns conditions for the solver to
            stop
        mass_matrix : array_like, optional
            The (sparse) mass matrix for the chosen spatial method.
        jacobian : method, optional
            A function that takes in t and y and returns the Jacobian. If
            None, the solver will approximate the Jacobian.
        """

        # A value that close to double rounding error, 1e-14 should work
        eps_rounding = 1e-14

        # Evaluate the Mass Matrix for dae-cpp solver
        if mass_matrix is not None:
            if sparse.issparse(mass_matrix):
                mass_eval = mass_matrix + eps_rounding * sparse.eye(y0.size)
            else:
                mass_eval = \
                    sparse.csr_matrix(mass_matrix) + eps_rounding * sparse.eye(y0.size)
            # make sure the matrix is in CSR format
            mass_eval = sparse.csr_matrix(mass_eval)
        else:
            # Defines identity mass matrix if mass_matrix is None
            mass_eval = sparse.csr_matrix(sparse.eye(y0.size))

        # dae-cpp Mass Matrix (created only once per solver call, since it does not
        # depend on time in dae-cpp)
        pydae_mass_holder = pydae.sparse_matrix_holder()
        isize = mass_eval.indptr.size
        jsize = mass_eval.data.size

        pydae_mass_holder.A.resize(jsize)
        pydae_mass_holder.ja.resize(jsize)
        pydae_mass_holder.ia.resize(isize)

        pydae_mass_holder.A[:] = pydae.state_type(mass_eval.data)
        pydae_mass_holder.ja[:] = pydae.vector_type_int(mass_eval.indices)
        pydae_mass_holder.ia[:] = pydae.vector_type_int(mass_eval.indptr)

        def fun_mass_matrix(M):
            M.A = pydae_mass_holder.A
            M.ia = pydae_mass_holder.ia
            M.ja = pydae_mass_holder.ja

        # dae-cpp RHS
        def fun_rhs(x, f, t):
            y = np.array(x)
            try:
                f[:] = pydae.state_type(residuals(t, y))
            except TypeError:
                ydot = np.zeros_like(y)
                f[:] = pydae.state_type(residuals(t, y, ydot))

        #def rootfn(t, y, ydot, return_root):
        #    return_root[:] = [event(t, y) for event in events]

        #extra_options = {"old_api": False, "rtol": self.tol, "atol": self.tol}

        # dae-cpp solver options
        opt = pydae.SolverOptions()
        opt.atol = self.tol
        opt.verbosity = 0
        opt.time_stepping = 1
        opt.dt_increase_threshold = 2

        dae_mass = pydae.MassMatrix(fun_mass_matrix)
        dae_rhs = pydae.RHS(fun_rhs)

        if jacobian:
            jac_y0_t0 = jacobian(t_eval[0], y0)

            if sparse.issparse(jac_y0_t0):
                def fun_jacobian(J, x, t):
                    jac_eval = jacobian(t, np.array(x)) + eps_rounding*sparse.eye(y0.size)

                    isize = jac_eval.indptr.size
                    jsize = jac_eval.data.size

                    J.A.resize(jsize)
                    J.ja.resize(jsize)
                    J.ia.resize(isize)

                    J.A[:] = pydae.state_type(jac_eval.data)
                    J.ja[:] = pydae.vector_type_int(jac_eval.indices)
                    J.ia[:] = pydae.vector_type_int(jac_eval.indptr)

                    #print("Sparse J.A: " + str(J.A))
                    #print("Sparse J.ia: " + str(J.ia))
                    #print("Sparse J.ja: " + str(J.ja))
            else:
                def fun_jacobian(J, x, t):
                    jac_eval = sparse.csr_matrix(jacobian(t, np.array(x))) + eps_rounding*sparse.eye(y0.size)

                    isize = jac_eval.indptr.size
                    jsize = jac_eval.data.size

                    J.A.resize(jsize)
                    J.ja.resize(jsize)
                    J.ia.resize(isize)

                    J.A[:] = pydae.state_type(jac_eval.data)
                    J.ja[:] = pydae.vector_type_int(jac_eval.indices)
                    J.ia[:] = pydae.vector_type_int(jac_eval.indptr)

                    #print("NON-Sparse J.A: " + str(J.A))
                    #print("NON-Sparse J.ia: " + str(J.ia))
                    #print("NON-Sparse J.ja: " + str(J.ja))

            dae_jacobian = pydae.AnalyticalJacobian(dae_rhs, fun_jacobian)
        else:
            dae_jacobian = pydae.NumericalJacobian(dae_rhs, self.tol)
            #print("numerical Jacobian")

        #if events:
        #    extra_options.update({"rootfn": rootfn, "nr_rootfns": len(events)})

        # set the solver up
        dae_solve = pydae.Solver(dae_rhs, dae_jacobian, dae_mass, opt)

        # initial condition
        x = pydae.state_type(y0)

        # solve
        first_pass = True
        status = -1
        for t1 in t_eval:
            # currently t1 cannot be 0 for dae-cpp.
            # TODO: remove this restriction in dae-cpp
            if t1 == 0:
                y_sol = np.reshape(np.array(x), (-1, 1))
                t_sol = np.array([0])
                first_pass = False
                continue
            else:
                # solution for time t1
                status = dae_solve(x, t1)  # x will be overwritten
                if status != 0:
                    break
                sol_t1 = np.reshape(np.array(x), (-1, 1))

            if first_pass:
                y_sol = sol_t1
                t_sol = np.array([t1])
                first_pass = False
            else:
                y_sol = np.append(y_sol, sol_t1, axis=1)
                t_sol = np.append(t_sol, t1)

        #dae_solver = scikits_odes.dae(self.method, eqsres, **extra_options)
        #sol = dae_solver.solve(t_eval, y0, ydot0)

        # return solution
        if status == 0:
            # success
            termination = "final time"
            return pybamm.Solution(t_sol, y_sol, termination)
        else:
            # error
            raise pybamm.SolverError("dae-cpp: Error during integration")

        # return solution, we need to tranpose y to match scipy's interface
        #if sol.flag in [0, 2]:
            # 0 = solved for all t_eval
        #    if sol.flag == 0:
        #        termination = "final time"
            # 2 = found root(s)
        #    elif sol.flag == 2:
        #        termination = "event"
        #    return pybamm.Solution(
        #        sol.values.t, np.transpose(sol.values.y), termination
        #    )
        #else:
        #    raise pybamm.SolverError(sol.message)