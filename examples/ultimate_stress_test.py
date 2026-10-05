"""Ultimate stress-test scene for manimgl-colab (ManimGL v1.7.2).

Five phases exercising almost every subsystem — all WITHOUT LaTeX:

  Phase 1  2D: NumberPlane, dynamic graph driven by a ValueTracker,
           always_redraw, glow dot glued to the curve, live DecimalNumber.
  Phase 2  Flow field: vectorized VectorField + animated StreamLines
           of a limit-cycle system.
  Phase 3  3D: Sphere -> Torus -> twisted ParametricSurface morphing
           with SurfaceMesh wireframes and camera reorientation.
  Phase 4  Lorenz attractor: three chaotic particles integrated live in
           an updater, TracingTail comet trails, ambient camera rotation.
  Phase 5  Time-driven rippling wave surface + fixed-in-frame HUD text.

Colab:
    %%manimgl -qm UltimateStressTest
    (paste this file's content below the magic line)
"""

from manimlib import *
import numpy as np


# ----------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------

def limit_cycle_flow(*args) -> np.ndarray:
    """2D flow with an attracting limit cycle of radius 2.

    Fully shape-agnostic, because ManimGL calls flow functions three ways:
      - VectorField:             func(batch_array_of_shape_n_by_d)
      - StreamLines ODE solver:  func(single_1d_state_vector)
      - StreamLines.init_style:  func(x, y) as separate scalars
    """
    if len(args) > 1:
        array = np.array(args, dtype=float)
    else:
        array = np.asarray(args[0], dtype=float)
    single = array.ndim == 1
    batch = array.reshape(1, -1) if single else array

    x, y = batch[:, 0], batch[:, 1]
    radial = 0.35 * (4.0 - (x ** 2 + y ** 2)) / 4.0
    out = np.zeros_like(batch)
    out[:, 0] = y + radial * x
    out[:, 1] = -x + radial * y
    return out[0] if single else out


def lorenz_derivative(point: np.ndarray,
                      sigma: float = 10.0,
                      rho: float = 28.0,
                      beta: float = 8.0 / 3.0) -> np.ndarray:
    """Classic Lorenz system, in attractor coordinates."""
    x, y, z = point
    return np.array([
        sigma * (y - x),
        x * (rho - z) - y,
        x * y - beta * z,
    ])


def twisted_shell(u: float, v: float) -> np.ndarray:
    """A twisted, flaring parametric shell (u, v in [0, 1])."""
    theta = TAU * u
    s = interpolate(-1.0, 1.0, v)
    radius = 2.0 + 0.6 * s * np.cos(2.5 * theta)
    return np.array([
        radius * np.cos(theta),
        radius * np.sin(theta),
        0.9 * s + 0.45 * np.sin(2.5 * theta) * s ** 2,
    ])


# ----------------------------------------------------------------------
# The scene
# ----------------------------------------------------------------------

class UltimateStressTest(ThreeDScene):
    def construct(self):
        self.phase_1_dynamic_graph()
        self.phase_2_flow_field()
        self.phase_3_surface_morph()
        self.phase_4_lorenz()
        self.phase_5_wave_finale()

    # ------------------------------------------------------------------
    # Phase 1 — 2D graphing, trackers, updaters
    # ------------------------------------------------------------------
    def phase_1_dynamic_graph(self):
        # ThreeDScene starts with a tilted default camera; 2D phases need flat.
        self.frame.reorient(0, 0)

        title = Text("Phase 1 — dynamic graph", font_size=34, color=YELLOW)
        title.to_corner(UL)

        plane = NumberPlane(
            x_range=(-6, 6, 1),
            y_range=(-3, 3, 1),
            background_line_style={
                "stroke_color": BLUE_D,
                "stroke_width": 1,
                "stroke_opacity": 0.6,
            },
        )

        frequency = ValueTracker(1.0)

        def damped_wave(x: float) -> float:
            return 2.2 * np.exp(-0.10 * x * x) * np.cos(frequency.get_value() * x)

        graph = always_redraw(
            lambda: plane.get_graph(damped_wave, color=TEAL, stroke_width=4)
        )

        dot = GlowDot(color=YELLOW, radius=0.35)
        dot.add_updater(
            lambda m: m.move_to(plane.input_to_graph_point(
                1.5 * np.cos(0.7 * frequency.get_value() * TAU),
                graph,
            ))
        )

        readout = DecimalNumber(1.0, num_decimal_places=2, color=YELLOW, font_size=40)
        readout.add_updater(lambda m: m.set_value(frequency.get_value()))
        readout_label = Text("frequency =", font_size=28)
        readout_group = VGroup(readout_label, readout)
        readout.next_to(readout_label, RIGHT, buff=0.2)
        readout_group.to_corner(UR)
        readout.add_updater(lambda m: m.next_to(readout_label, RIGHT, buff=0.2))

        self.play(Write(title), ShowCreation(plane, lag_ratio=0.02), run_time=1.6)
        self.add(graph, dot, readout_group)
        self.play(frequency.animate.set_value(4.0), run_time=2.6, rate_func=there_and_back)
        self.play(frequency.animate.set_value(2.5), run_time=1.2)

        graph.clear_updaters()
        dot.clear_updaters()
        readout.clear_updaters()
        self.play(
            *(FadeOut(mobject) for mobject in (graph, dot, readout_group, title)),
            plane.animate.set_stroke(opacity=0.25),
            run_time=0.9,
        )
        self.plane = plane

    # ------------------------------------------------------------------
    # Phase 2 — vector field + animated stream lines
    # ------------------------------------------------------------------
    def phase_2_flow_field(self):
        title = Text("Phase 2 — flow field", font_size=34, color=YELLOW)
        title.to_corner(UL)

        field = VectorField(
            limit_cycle_flow,
            self.plane,
            density=1.4,
            stroke_width=3,
            magnitude_range=(0, 3),
        )
        stream_lines = StreamLines(
            limit_cycle_flow,
            self.plane,
            density=1.0,
            solution_time=2.5,
            stroke_width=2.5,
            magnitude_range=(0, 3),
        )
        animated_lines = AnimatedStreamLines(stream_lines)

        self.play(FadeIn(title), GrowFromCenter(field, lag_ratio=0.01), run_time=1.4)
        self.add(animated_lines)
        self.wait(3.0)
        self.play(
            FadeOut(field),
            FadeOut(animated_lines),
            FadeOut(title),
            FadeOut(self.plane),
            run_time=0.9,
        )

    # ------------------------------------------------------------------
    # Phase 3 — morphing 3D surfaces
    # ------------------------------------------------------------------
    def phase_3_surface_morph(self):
        title = Text("Phase 3 — surface morphing", font_size=34, color=YELLOW)
        title.to_corner(UL)
        title.fix_in_frame()

        self.play(FadeIn(title), run_time=0.5)
        self.play(self.frame.animate.reorient(28, 68), run_time=1.4)

        def dressed(surface: Surface, mesh_color) -> Group:
            surface.set_opacity(0.9)
            surface.set_shading(0.35, 0.55, 0.25)
            mesh = SurfaceMesh(surface, resolution=(21, 21))
            mesh.set_stroke(mesh_color, width=0.8, opacity=0.5)
            return Group(surface, mesh)

        sphere = dressed(Sphere(radius=2.1, color=BLUE_D), BLUE_A)
        torus = dressed(Torus(r1=2.1, r2=0.75, color=TEAL_D), TEAL_A)
        shell = dressed(
            ParametricSurface(twisted_shell, resolution=(60, 20), color=PURPLE_C),
            PURPLE_A,
        )

        self.play(FadeIn(sphere, scale=0.6), run_time=1.2)
        self.play(Rotate(sphere, PI / 2, axis=UP), run_time=1.2)
        self.play(ReplacementTransform(sphere, torus), run_time=1.8)
        self.play(Rotate(torus, PI / 2, axis=RIGHT + 0.3 * UP), run_time=1.6)
        self.play(ReplacementTransform(torus, shell), run_time=1.8)
        self.play(
            Rotate(shell, TAU, axis=OUT),
            self.frame.animate.reorient(-25, 75),
            run_time=3.0,
            rate_func=smooth,
        )
        self.play(FadeOut(shell), FadeOut(title), run_time=0.8)

    # ------------------------------------------------------------------
    # Phase 4 — Lorenz attractor, live ODE integration
    # ------------------------------------------------------------------
    def phase_4_lorenz(self):
        title = Text("Phase 4 — Lorenz attractor", font_size=34, color=YELLOW)
        title.to_corner(UL)
        title.fix_in_frame()

        scale = 0.14
        center_shift = np.array([0.0, 0.0, -3.4])

        def to_scene(point: np.ndarray) -> np.ndarray:
            return point * scale + center_shift

        self.play(FadeIn(title), self.frame.animate.reorient(40, 62), run_time=1.0)

        colors = [RED_B, GOLD_B, BLUE_B]
        seeds = [
            np.array([10.0, 10.0, 25.0]),
            np.array([10.01, 10.0, 25.0]),
            np.array([10.0, 10.01, 25.0]),
        ]
        # Pre-warm each trajectory past the initial transient so the
        # butterfly shape appears immediately.
        for index, seed in enumerate(seeds):
            state = seed.copy()
            for _ in range(400):
                state = state + 0.004 * lorenz_derivative(state)
            seeds[index] = state

        particles = Group()
        trails = []
        for color, seed in zip(colors, seeds):
            dot = GlowDot(color=color, radius=0.25)
            dot.state = seed.copy()
            dot.move_to(to_scene(dot.state))

            def integrate(mobject, dt, _unused=None):
                steps = max(1, int(dt / 0.004))
                h = dt / steps
                for _ in range(steps):
                    k1 = lorenz_derivative(mobject.state)
                    k2 = lorenz_derivative(mobject.state + 0.5 * h * k1)
                    mobject.state = mobject.state + h * k2
                mobject.move_to(to_scene(mobject.state))

            dot.add_updater(integrate)
            particles.add(dot)
            trail = TracingTail(
                dot,
                time_traced=6.0,
                stroke_color=color,
                stroke_width=(0, 4),
            )
            trails.append(trail)

        self.frame.add_ambient_rotation(10 * DEG)
        self.add(*trails, particles)
        self.wait(10.0)

        for dot in particles:
            dot.clear_updaters()
        self.frame.clear_updaters()
        self.play(
            *(FadeOut(mobject) for mobject in (*trails, particles, title)),
            run_time=0.9,
        )

    # ------------------------------------------------------------------
    # Phase 5 — time-driven rippling surface finale
    # ------------------------------------------------------------------
    def phase_5_wave_finale(self):
        title = Text("Phase 5 — ripple finale", font_size=34, color=YELLOW)
        title.to_corner(UL)
        title.fix_in_frame()

        time_tracker = ValueTracker(0.0)

        def ripple_surface() -> ParametricSurface:
            t = time_tracker.get_value()

            def uv_func(u: float, v: float) -> np.ndarray:
                x = interpolate(-4.0, 4.0, u)
                y = interpolate(-4.0, 4.0, v)
                r = np.sqrt(x * x + y * y)
                z = 0.85 * np.sin(2.0 * r - 2.4 * t) * np.exp(-0.18 * r)
                return np.array([x, y, z])

            surface = ParametricSurface(uv_func, resolution=(28, 28))
            surface.set_color(BLUE_D)
            surface.set_opacity(0.92)
            surface.set_shading(0.3, 0.6, 0.2)
            return surface

        surface = always_redraw(ripple_surface)

        self.play(
            FadeIn(title),
            self.frame.animate.reorient(30, 60),
            run_time=1.0,
        )
        self.add(surface)
        self.play(
            time_tracker.animate.set_value(TAU),
            self.frame.animate.reorient(-20, 52),
            run_time=5.0,
            rate_func=linear,
        )
        surface.clear_updaters()

        banner = Text(
            "manimgl-colab  —  all systems passed",
            font_size=44,
            color=GREEN_B,
        )
        banner.fix_in_frame()
        self.play(FadeOut(surface), FadeOut(title), run_time=0.7)
        self.play(Write(banner), run_time=1.5)
        self.wait(1.0)
        self.play(FadeOut(banner), run_time=0.7)
