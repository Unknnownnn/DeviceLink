import customtkinter as ctk
import math
import random
import time

ctk.set_appearance_mode("dark")

WIDTH = 900
HEIGHT = 700

BG = "#0b0f14"
CYAN = "#00e5ff"
TEXT = "#aeb6c2"


class NeuralIdle(ctk.CTkCanvas):

    def __init__(self, master):

        super().__init__(
            master,
            width=WIDTH,
            height=HEIGHT,
            bg=BG,
            highlightthickness=0
        )

        self.start_time = time.time()

        self.cx = WIDTH / 2
        self.cy = HEIGHT / 2

        # --------------------------
        # Create wandering particles
        # --------------------------

        self.particles = []

        for _ in range(10):

            angle = random.uniform(0, math.pi * 2)
            distance = random.uniform(90, 200)

            x = self.cx + math.cos(angle) * distance
            y = self.cy + math.sin(angle) * distance

            self.particles.append({
                "x": x,
                "y": y,
                "vx": random.uniform(-0.25, 0.25),
                "vy": random.uniform(-0.25, 0.25),
                "size": random.uniform(1.5, 3)
            })

        self.animate()

    # --------------------------------
    # Draw soft glowing core
    # --------------------------------

    def draw_core(self, x, y, radius):

        self.create_oval(
            x-radius*3,
            y-radius*3,
            x+radius*3,
            y+radius*3,
            fill="#07262d",
            outline=""
        )

        self.create_oval(
            x-radius*2,
            y-radius*2,
            x+radius*2,
            y+radius*2,
            fill="#0a3c47",
            outline=""
        )

        self.create_oval(
            x-radius,
            y-radius,
            x+radius,
            y+radius,
            fill=CYAN,
            outline=""
        )

    # --------------------------------
    # Main Animation
    # --------------------------------

    def animate(self):

        self.delete("all")

        t = time.time() - self.start_time

        # --------------------------------
        # Center core breathing
        # --------------------------------

        breathing = 8 + 0.8 * math.sin(t * 0.45)

        self.draw_core(
            self.cx,
            self.cy,
            breathing
        )

        # --------------------------------
        # Random drifting particles
        # --------------------------------

        for particle in self.particles:

            dx = self.cx - particle["x"]
            dy = self.cy - particle["y"]

            distance = math.sqrt(dx * dx + dy * dy)

            # Keep particles within a loose boundary

            if distance > 220:

                particle["vx"] += dx * 0.0007
                particle["vy"] += dy * 0.0007

            # Random wandering

            particle["vx"] += random.uniform(-0.015, 0.015)
            particle["vy"] += random.uniform(-0.015, 0.015)

            # Gentle damping

            particle["vx"] *= 0.995
            particle["vy"] *= 0.995

            # Move particle

            particle["x"] += particle["vx"]
            particle["y"] += particle["vy"]

            r = particle["size"]

            # Soft glow

            self.create_oval(
                particle["x"] - r * 2,
                particle["y"] - r * 2,
                particle["x"] + r * 2,
                particle["y"] + r * 2,
                fill="#103843",
                outline=""
            )

            # Particle

            self.create_oval(
                particle["x"] - r,
                particle["y"] - r,
                particle["x"] + r,
                particle["y"] + r,
                fill=CYAN,
                outline=""
            )

        # --------------------------------
        # Status text
        # --------------------------------

        dots = int((t * 1.2) % 4)

        self.create_text(
            self.cx,
            self.cy + 250,
            text="Awaiting Input" + "." * dots,
            fill=TEXT,
            font=("Segoe UI", 14)
        )

        self.after(16, self.animate)


class App(ctk.CTk):

    def __init__(self):

        super().__init__()

        self.title("AI Agent Idle")

        self.geometry("900x700")

        self.configure(
            fg_color=BG
        )

        self.animation = NeuralIdle(self)

        self.animation.pack(
            fill="both",
            expand=True
        )


if __name__ == "__main__":

    app = App()

    app.mainloop()