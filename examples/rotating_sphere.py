from manimlib import *


class RotatingSphere(ThreeDScene):
    def construct(self):
        self.frame.reorient(25, 70)

        sphere = Sphere(radius=2.2, resolution=(25, 25))
        sphere.set_color(BLUE_D)
        sphere.set_opacity(0.95)
        sphere.set_shading(0.35, 0.55, 0.25)

        mesh = SurfaceMesh(sphere, resolution=(25, 25))
        mesh.set_stroke(BLUE_A, width=0.8, opacity=0.55)
        sphere.add(mesh)

        self.play(FadeIn(sphere), run_time=1)
        self.play(
            Rotate(sphere, angle=TAU, axis=UP + 0.25 * RIGHT),
            run_time=5,
            rate_func=linear,
        )
        self.wait(1)
