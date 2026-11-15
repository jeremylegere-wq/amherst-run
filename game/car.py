"""Arcade car physics (top-down, metres and seconds).

Heading 0 points east (+x); y grows south, so a positive heading change turns
clockwise on screen. Velocity is split into a forward part and a sideways part;
the sideways part decays quickly (grip), which gives drifting when grip drops.
"""
import math

LENGTH = 4.2
WIDTH = 1.8

ACCEL = 18.0          # m/s^2 at standstill
BRAKE = 32.0          # m/s^2
REVERSE_MAX = 9.0
MAX_SPEED_ROAD = 38.0  # ~137 km/h
MAX_SPEED_GRASS = 15.0
DRAG = 0.05           # 1/s, proportional drag (top speed settles near 34 m/s, ~124 km/h)
ROLLING = 2.5         # m/s^2, constant slow-down when coasting
GRIP_ROAD = 9.0       # 1/s sideways velocity decay
GRIP_GRASS = 4.5
GRIP_HANDBRAKE = 1.2
STEER_RATE = 2.4      # rad/s at low speed

HOP_SPEED = 4.6       # m/s upward at the start of a bumper hop (about 0.5 m high, 0.4 s in the air)
HOP_GRAVITY = 24.0
DRIFT_MIN_SPEED = 9.0  # m/s needed to start a power slide
DRIFT_GRIP = 2.3      # sideways grip while sliding (road grip is 9): the back end swings out
DRIFT_SLIDE = 0.4     # how much of each turn the velocity does not follow
DRIFT_TURN = 1.45     # extra turn rate while sliding
CHARGE_STEPS = ((0.8, 0.6), (1.6, 1.1), (2.6, 1.7))   # (slide seconds, boost seconds): blue, orange, purple
BOOST_SPEED = 1.28    # top speed multiplier while boosting
BOOST_ACCEL = 34.0
BOOST_KICK = 3.0      # instant m/s added when the boost fires

# Colours used by the renderers (an AI car gets its own palette)
PLAYER_PALETTE = {
    "body": (244, 220, 60), "lower": (30, 30, 40), "glass": (70, 100, 170),
    "tail": (232, 40, 40), "roof": (244, 220, 60), "lightbar": False,
}


# Player vehicles (original low-poly shapes, no badges). length/width in metres drive collisions too;
# cabin = (rear, front) of the glass box, z = (belt line, roof height).
MODELS = {
    "sedan": dict(length=4.2, width=1.8, mass=1.0, power=1.0, cab=(-1.3, 0.85), cab_top=(-1.0, 0.4), z=(0.95, 1.62),
                  ride=0.3, wheel=1.35, bed=None, spare=False),
    "fj": dict(length=4.6, width=1.9, mass=1.25, power=1.0, cab=(-2.0, 1.0), cab_top=(-1.95, 0.8), z=(1.2, 1.95),
               ride=0.42, wheel=1.45, bed=None, spare=True),
    "crv": dict(length=4.6, width=1.85, mass=1.1, power=1.02, cab=(-2.0, 0.9), cab_top=(-1.7, 0.2), z=(1.12, 1.8),
                ride=0.34, wheel=1.45, bed=None, spare=False),
    "sorento": dict(length=4.8, width=1.9, mass=1.3, power=1.03, cab=(-2.1, 0.9), cab_top=(-1.9, 0.3), z=(1.18, 1.88),
                    ride=0.38, wheel=1.5, bed=None, spare=False),
    "ram": dict(length=5.9, width=2.0, mass=1.65, power=0.97, cab=(-0.5, 1.55), cab_top=(-0.3, 0.95), z=(1.2, 2.05),
                ride=0.5, wheel=1.9, bed=(-2.95, -0.55), spare=False),
}
PLAYER_MODELS = ("fj", "crv", "sorento", "ram")          # player 1..4
PLAYER_LOOKS = {                                         # body, roof, glass, tail light
    "fj": ((240, 214, 66), (246, 246, 240), (60, 84, 130), (222, 40, 40)),
    "crv": ((238, 238, 234), (238, 238, 234), (70, 96, 150), (222, 40, 40)),
    "sorento": ((128, 134, 144), (128, 134, 144), (60, 84, 130), (222, 40, 40)),
    "ram": ((40, 42, 50), (40, 42, 50), (74, 96, 140), (222, 40, 40)),
}


def player_car(index, x=0.0, y=0.0, heading=0.0):
    """Car for human player `index` (0-3): boxy retro SUV, compact crossover, mid-size SUV, quad cab pickup."""
    model = PLAYER_MODELS[index % 4]
    body, roof, glass, tail = PLAYER_LOOKS[model]
    c = Car(x, y, heading, model=model)
    c.palette = {"body": body, "lower": (30, 30, 40), "glass": glass, "tail": tail, "roof": roof, "lightbar": False}
    return c


class Car:
    kind = "player"           # town code asks every car what it is (AI cars set "traffic" or "police")

    def __init__(self, x=0.0, y=0.0, heading=0.0, model="sedan"):
        self.x, self.y, self.heading = x, y, heading
        self.model = model
        spec = MODELS[model]
        self.spec = spec
        self.length, self.width = spec["length"], spec["width"]
        self.power_scale = spec["power"]
        self.hop_z = self.hop_vz = 0.0          # bumper hop (visual height in metres)
        self.drift = 0                          # 0 = not sliding, else -1/+1 = slide direction
        self.charge = 0.0                       # seconds of sliding so far
        self.boost_t = 0.0
        self._bumper_prev = False
        self.vx = self.vy = 0.0
        self.z = 0.0          # height above the ground (on an overpass)
        self.power = 1.0      # 1.0 = undamaged; scales acceleration and top speed
        self.mass = spec["mass"]   # relative mass for car-vs-car collisions
        self.palette = PLAYER_PALETTE

    # --- helpers -----------------------------------------------------------
    @property
    def forward(self):
        return math.cos(self.heading), math.sin(self.heading)

    @property
    def right(self):
        return -math.sin(self.heading), math.cos(self.heading)

    @property
    def speed(self):
        return math.hypot(self.vx, self.vy)

    def forward_speed(self):
        fx, fy = self.forward
        return self.vx * fx + self.vy * fy

    def corners(self):
        fx, fy = self.forward
        rx, ry = self.right
        hl, hw = self.length / 2, self.width / 2
        return [(self.x + fx * a + rx * b, self.y + fy * a + ry * b)
                for a, b in ((hl, -hw), (hl, hw), (-hl, hw), (-hl, -hw))]

    # --- simulation --------------------------------------------------------
    @property
    def charge_level(self):
        """0-3: how many boost levels the current slide has charged (blue, orange, purple)."""
        return sum(1 for need, _b in CHARGE_STEPS if self.charge >= need)

    def _hop_and_drift(self, dt, steer, bumper, vf):
        """Bumper = hop. Hop while steering at speed and you start a power slide; hold it to charge, let go to boost."""
        pressed = bumper and not self._bumper_prev
        self._bumper_prev = bumper
        if pressed and self.hop_z <= 0.0 and self.hop_vz <= 0.0 and abs(vf) > 3.0:
            self.hop_vz = HOP_SPEED
            if abs(steer) > 0.3 and vf > DRIFT_MIN_SPEED and not self.drift:
                self.drift = 1 if steer > 0 else -1
                self.charge = 0.0
        if self.hop_vz != 0.0 or self.hop_z > 0.0:
            self.hop_vz -= HOP_GRAVITY * dt
            self.hop_z += self.hop_vz * dt
            if self.hop_z <= 0.0:
                self.hop_z = self.hop_vz = 0.0
        if not self.drift and bumper and self.hop_z <= 0.0 and vf > DRIFT_MIN_SPEED and abs(steer) > 0.6:
            self.drift = 1 if steer > 0 else -1             # holding the bumper while turning also starts a slide
            self.charge = 0.0
        if self.drift:
            if not bumper or vf < DRIFT_MIN_SPEED * 0.6:
                level = self.charge_level
                if level:
                    self.boost_t = CHARGE_STEPS[level - 1][1]
                    self.vx += self.forward[0] * BOOST_KICK
                    self.vy += self.forward[1] * BOOST_KICK
                self.drift, self.charge = 0, 0.0
            else:
                inward = max(0.0, steer * self.drift)
                self.charge = min(CHARGE_STEPS[-1][0] + 0.4, self.charge + dt * (1.0 + 0.5 * inward))

    def update(self, dt, throttle, brake, steer, handbrake, on_road, bumper=False):
        fx, fy = self.forward
        rx, ry = self.right
        vf = self.vx * fx + self.vy * fy
        vl = self.vx * rx + self.vy * ry
        self._hop_and_drift(dt, steer, bumper, vf)
        boosting = self.boost_t > 0.0
        if boosting:
            self.boost_t = max(0.0, self.boost_t - dt)
        max_speed = (MAX_SPEED_ROAD if on_road else MAX_SPEED_GRASS) * self.power * self.power_scale
        if boosting:
            max_speed *= BOOST_SPEED

        # engine and brakes
        if boosting:
            vf += BOOST_ACCEL * (1.0 - max(0.0, min(1.0, vf / max_speed))) * dt
        elif throttle:
            vf += ACCEL * self.power * (1.0 - max(0.0, min(1.0, vf / max_speed))) * dt
        if brake:
            if vf > 0.5:
                vf = max(0.0, vf - BRAKE * dt)
            else:
                vf = max(-REVERSE_MAX, vf - ACCEL * 0.6 * dt)
        if not throttle and not brake:
            roll = ROLLING * dt
            vf = 0.0 if abs(vf) <= roll else vf - math.copysign(roll, vf)
        vf -= vf * DRAG * dt
        if vf > max_speed:  # off-road speed cap, bleeds off quickly
            vf -= (vf - max_speed) * 3.0 * dt

        # sideways grip: handbrake lets the back end slide
        grip = GRIP_HANDBRAKE if handbrake else (GRIP_ROAD if on_road else GRIP_GRASS)
        if self.drift:
            grip = min(grip, DRIFT_GRIP)
        vl *= math.exp(-grip * dt)

        # steering: less turn at speed, none when stationary, flipped in reverse
        turn = steer * STEER_RATE / (1.0 + abs(vf) / 16.0) * min(1.0, abs(vf) / 3.0)
        if handbrake:
            turn *= 1.5
        if self.drift:                        # slide direction is locked; steering in tightens it, out widens it
            turn = self.drift * (1.0 + 0.45 * steer * self.drift) * STEER_RATE * DRIFT_TURN / (1.0 + abs(vf) / 16.0)
        dtheta = turn * math.copysign(1.0, vf if abs(vf) > 0.01 else 1.0) * dt
        self.heading += dtheta
        if self.drift:
            vl -= vf * dtheta * DRIFT_SLIDE            # the velocity lags behind the nose: the car visibly slides

        fx, fy = self.forward
        rx, ry = self.right
        self.vx = fx * vf + rx * vl
        self.vy = fy * vf + ry * vl
        self.x += self.vx * dt
        self.y += self.vy * dt

    def bump(self, prev_x, prev_y):
        """Undo the last move after a collision and lose most of the speed."""
        self.x, self.y = prev_x, prev_y
        self.vx *= -0.3
        self.vy *= -0.3
