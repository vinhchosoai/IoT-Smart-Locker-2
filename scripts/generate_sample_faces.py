"""
Generates sample portrait face images for Hybrid Simulation Kiosk testing & automated TC verification.
Includes multiple distinct customers (each with check-in and check-out captures) and an invalid/no-face sample.
"""

from pathlib import Path
from typing import Dict, Tuple
import cv2
import numpy as np

from backend.config import SAMPLE_FACES_DIR


def _draw_portrait(
    bg_color: Tuple[int, int, int],
    skin_bgr: Tuple[int, int, int],
    hair_bgr: Tuple[int, int, int],
    shirt_bgr: Tuple[int, int, int],
    eye_bgr: Tuple[int, int, int],
    lip_bgr: Tuple[int, int, int],
    face_rx: int,
    face_ry: int,
    eye_spacing: int,
    eye_y_offset: int,
    brow_thickness: int,
    brow_arch: int,
    nose_len: int,
    nose_width: int,
    mouth_width: int,
    mouth_curve: int,
    hair_style: str,
    glasses: bool = False,
    beard: bool = False,
    mole_pos: Tuple[int, int] = (0, 0),
    shift_x: int = 0,
    shift_y: int = 0,
    brightness_delta: int = 0,
    seed: int = 42,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    w, h = 400, 440
    img = np.full((h, w, 3), bg_color, dtype=np.uint8)

    # Subtle background gradient
    for y in range(h):
        ratio = y / float(h)
        img[y, :] = np.clip(
            np.array(bg_color) * (1.0 - 0.25 * ratio), 0, 255
        ).astype(np.uint8)

    cx = w // 2 + shift_x
    cy = h // 2 + shift_y

    # Shoulders / shirt
    cv2.ellipse(
        img,
        (cx, h + 10),
        (150, 110),
        0,
        180,
        360,
        shirt_bgr,
        -1,
        cv2.LINE_AA,
    )

    # Neck
    neck_color = tuple(max(0, c - 18) for c in skin_bgr)
    cv2.rectangle(
        img,
        (cx - 34, cy + face_ry - 25),
        (cx + 34, cy + face_ry + 45),
        neck_color,
        -1,
    )

    # Back hair for long style
    if hair_style == "long":
        cv2.ellipse(
            img,
            (cx, cy + 15),
            (face_rx + 26, face_ry + 45),
            0,
            0,
            360,
            hair_bgr,
            -1,
            cv2.LINE_AA,
        )

    # Ears
    cv2.ellipse(
        img,
        (cx - face_rx - 4, cy + 5),
        (14, 28),
        0,
        0,
        360,
        neck_color,
        -1,
        cv2.LINE_AA,
    )
    cv2.ellipse(
        img,
        (cx + face_rx + 4, cy + 5),
        (14, 28),
        0,
        0,
        360,
        neck_color,
        -1,
        cv2.LINE_AA,
    )

    # Main Face Oval
    cv2.ellipse(
        img,
        (cx, cy),
        (face_rx, face_ry),
        0,
        0,
        360,
        skin_bgr,
        -1,
        cv2.LINE_AA,
    )

    # Facial shading (cheekbones & forehead highlight for realistic 3D gradient)
    shade = np.zeros_like(img, dtype=np.float32)
    cv2.circle(shade, (cx - face_rx // 2, cy + 18), 32, (12, 16, 28), -1)
    cv2.circle(shade, (cx + face_rx // 2, cy + 18), 32, (12, 16, 28), -1)
    cv2.ellipse(shade, (cx, cy - face_ry // 2), (45, 22), 0, 0, 360, (-14, -14, -14), -1)
    shade = cv2.GaussianBlur(shade, (31, 31), 12)
    img = np.clip(img.astype(np.float32) - shade, 0, 255).astype(np.uint8)

    # Beard / stubble if enabled
    if beard:
        beard_overlay = img.copy()
        cv2.ellipse(
            beard_overlay,
            (cx, cy + 25),
            (face_rx - 6, face_ry - 18),
            0,
            15,
            165,
            hair_bgr,
            -1,
            cv2.LINE_AA,
        )
        img = cv2.addWeighted(beard_overlay, 0.38, img, 0.62, 0)

    # Hair top
    if hair_style == "short_part":
        cv2.ellipse(
            img,
            (cx, cy - face_ry + 18),
            (face_rx + 8, 52),
            0,
            170,
            370,
            hair_bgr,
            -1,
            cv2.LINE_AA,
        )
        # Side part cut
        cv2.line(
            img,
            (cx - 38, cy - face_ry - 5),
            (cx - 24, cy - face_ry + 32),
            skin_bgr,
            4,
            cv2.LINE_AA,
        )
    elif hair_style == "long":
        cv2.ellipse(
            img,
            (cx, cy - face_ry + 22),
            (face_rx + 18, 60),
            0,
            160,
            380,
            hair_bgr,
            -1,
            cv2.LINE_AA,
        )
        cv2.ellipse(
            img,
            (cx - face_rx + 10, cy - 25),
            (26, 75),
            20,
            0,
            360,
            hair_bgr,
            -1,
            cv2.LINE_AA,
        )
        cv2.ellipse(
            img,
            (cx + face_rx - 10, cy - 25),
            (26, 75),
            -20,
            0,
            360,
            hair_bgr,
            -1,
            cv2.LINE_AA,
        )
    elif hair_style == "spiky":
        cv2.ellipse(
            img,
            (cx, cy - face_ry + 12),
            (face_rx + 4, 42),
            0,
            175,
            365,
            hair_bgr,
            -1,
            cv2.LINE_AA,
        )
        for sx in range(-60, 70, 24):
            pts = np.array(
                [
                    [cx + sx - 16, cy - face_ry + 15],
                    [cx + sx, cy - face_ry - 32],
                    [cx + sx + 16, cy - face_ry + 15],
                ],
                np.int32,
            )
            cv2.fillPoly(img, [pts], hair_bgr, cv2.LINE_AA)
    else:  # buzz / curly
        cv2.ellipse(
            img,
            (cx, cy - face_ry + 25),
            (face_rx + 6, 48),
            0,
            175,
            365,
            hair_bgr,
            -1,
            cv2.LINE_AA,
        )

    # Eyebrows
    ey = cy + eye_y_offset
    lx = cx - eye_spacing
    rx = cx + eye_spacing

    brow_pts_l = np.array(
        [
            [lx - 26, ey - 20],
            [lx, ey - 24 - brow_arch],
            [lx + 24, ey - 18],
        ],
        np.int32,
    )
    brow_pts_r = np.array(
        [
            [rx - 24, ey - 18],
            [rx, ey - 24 - brow_arch],
            [rx + 26, ey - 20],
        ],
        np.int32,
    )
    cv2.polylines(img, [brow_pts_l], False, hair_bgr, brow_thickness, cv2.LINE_AA)
    cv2.polylines(img, [brow_pts_r], False, hair_bgr, brow_thickness, cv2.LINE_AA)

    # Eye sockets shadow (crucial for Haar Cascade frontal face detection!)
    socket_overlay = img.copy()
    cv2.ellipse(socket_overlay, (lx, ey), (26, 16), 0, 0, 360, (35, 40, 55), -1)
    cv2.ellipse(socket_overlay, (rx, ey), (26, 16), 0, 0, 360, (35, 40, 55), -1)
    img = cv2.addWeighted(socket_overlay, 0.25, img, 0.75, 0)

    # Sclera & Iris & Pupil
    for ex in (lx, rx):
        cv2.ellipse(img, (ex, ey), (19, 11), 0, 0, 360, (245, 245, 248), -1, cv2.LINE_AA)
        cv2.circle(img, (ex, ey), 9, eye_bgr, -1, cv2.LINE_AA)
        cv2.circle(img, (ex, ey), 4, (12, 12, 12), -1, cv2.LINE_AA)
        cv2.circle(img, (ex - 3, ey - 3), 2, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.ellipse(img, (ex, ey), (19, 11), 0, 180, 360, (25, 25, 30), 2, cv2.LINE_AA)

    # Glasses if enabled
    if glasses:
        cv2.rectangle(img, (lx - 28, ey - 16), (lx + 28, ey + 16), (30, 30, 35), 3, cv2.LINE_AA)
        cv2.rectangle(img, (rx - 28, ey - 16), (rx + 28, ey + 16), (30, 30, 35), 3, cv2.LINE_AA)
        cv2.line(img, (lx + 28, ey - 2), (rx - 28, ey - 2), (30, 30, 35), 3, cv2.LINE_AA)

    # Nose bridge & nostrils
    ny_top = ey + 6
    ny_bot = ny_top + nose_len
    nose_shadow = tuple(max(0, c - 38) for c in skin_bgr)
    cv2.line(img, (cx - 4, ny_top), (cx - nose_width // 2, ny_bot), nose_shadow, 2, cv2.LINE_AA)
    cv2.line(img, (cx + 4, ny_top), (cx + nose_width // 2, ny_bot), nose_shadow, 2, cv2.LINE_AA)
    cv2.ellipse(
        img,
        (cx, ny_bot + 2),
        (nose_width, 9),
        0,
        0,
        180,
        nose_shadow,
        2,
        cv2.LINE_AA,
    )
    cv2.circle(img, (cx - nose_width // 2 + 3, ny_bot + 2), 4, (45, 50, 65), -1, cv2.LINE_AA)
    cv2.circle(img, (cx + nose_width // 2 - 3, ny_bot + 2), 4, (45, 50, 65), -1, cv2.LINE_AA)

    # Mouth & Lips
    my = ny_bot + 34
    cv2.ellipse(
        img,
        (cx, my),
        (mouth_width, abs(mouth_curve) + 8),
        0,
        0,
        180 if mouth_curve >= 0 else 360,
        lip_bgr,
        -1,
        cv2.LINE_AA,
    )
    cv2.line(
        img,
        (cx - mouth_width, my + 2),
        (cx + mouth_width, my + 2),
        (35, 30, 60),
        2,
        cv2.LINE_AA,
    )

    if mole_pos != (0, 0):
        cv2.circle(
            img,
            (cx + mole_pos[0], cy + mole_pos[1]),
            3,
            (35, 45, 65),
            -1,
            cv2.LINE_AA,
        )

    # Apply subtle camera sensor grain & brightness variation
    noise = rng.normal(brightness_delta, 2.2, img.shape).astype(np.float32)
    img = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return img


def generate_all_sample_faces(target_dir: Path = SAMPLE_FACES_DIR) -> Dict[str, Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, Path] = {}

    # Customer 1: Nguyễn Văn An (Short parted hair, warm skin, no glasses)
    c1_params = dict(
        bg_color=(225, 195, 165),
        skin_bgr=(168, 198, 232),
        hair_bgr=(28, 32, 40),
        shirt_bgr=(150, 75, 35),
        eye_bgr=(42, 65, 95),
        lip_bgr=(115, 118, 195),
        face_rx=88,
        face_ry=112,
        eye_spacing=38,
        eye_y_offset=-14,
        brow_thickness=5,
        brow_arch=6,
        nose_len=42,
        nose_width=18,
        mouth_width=32,
        mouth_curve=6,
        hair_style="short_part",
        glasses=False,
        beard=False,
        mole_pos=(-32, 28),
    )
    img_c1_a = _draw_portrait(**c1_params, shift_x=0, shift_y=0, brightness_delta=0, seed=101)
    img_c1_b = _draw_portrait(**c1_params, shift_x=2, shift_y=-1, brightness_delta=4, seed=102)

    # Customer 2: Trần Thị Bình (Long dark-brown hair, lighter warm skin, red lips, arched brows)
    c2_params = dict(
        bg_color=(230, 215, 180),
        skin_bgr=(180, 206, 240),
        hair_bgr=(35, 55, 95),
        shirt_bgr=(145, 75, 115),
        eye_bgr=(65, 85, 55),
        lip_bgr=(85, 80, 215),
        face_rx=78,
        face_ry=104,
        eye_spacing=34,
        eye_y_offset=-10,
        brow_thickness=3,
        brow_arch=12,
        nose_len=35,
        nose_width=14,
        mouth_width=26,
        mouth_curve=9,
        hair_style="long",
        glasses=False,
        beard=False,
        mole_pos=(26, 18),
    )
    img_c2_a = _draw_portrait(**c2_params, shift_x=0, shift_y=0, brightness_delta=0, seed=201)
    img_c2_b = _draw_portrait(**c2_params, shift_x=-2, shift_y=1, brightness_delta=-3, seed=202)

    # Customer 3: Lê Hoàng Cường (Spiky hair, glasses, beard, olive/tan skin)
    c3_params = dict(
        bg_color=(205, 220, 185),
        skin_bgr=(132, 168, 208),
        hair_bgr=(18, 20, 22),
        shirt_bgr=(45, 110, 65),
        eye_bgr=(30, 40, 55),
        lip_bgr=(95, 105, 165),
        face_rx=95,
        face_ry=118,
        eye_spacing=42,
        eye_y_offset=-18,
        brow_thickness=7,
        brow_arch=2,
        nose_len=48,
        nose_width=23,
        mouth_width=38,
        mouth_curve=2,
        hair_style="spiky",
        glasses=True,
        beard=True,
        mole_pos=(0, 0),
    )
    img_c3_a = _draw_portrait(**c3_params, shift_x=0, shift_y=0, brightness_delta=0, seed=301)
    img_c3_b = _draw_portrait(**c3_params, shift_x=1, shift_y=2, brightness_delta=3, seed=302)

    # Customer 4: Phạm Minh Dũng (Stranger - Distinct complexion, wide round face, glasses, thick brows)
    c4_params = dict(
        bg_color=(215, 200, 190),
        skin_bgr=(125, 160, 202),
        hair_bgr=(65, 155, 225),
        shirt_bgr=(165, 65, 55),
        eye_bgr=(185, 125, 35),
        lip_bgr=(75, 70, 195),
        face_rx=104,
        face_ry=96,
        eye_spacing=46,
        eye_y_offset=4,
        brow_thickness=8,
        brow_arch=-4,
        nose_len=28,
        nose_width=26,
        mouth_width=44,
        mouth_curve=-8,
        hair_style="long",
        glasses=True,
        beard=False,
        mole_pos=(-40, -10),
    )
    img_c4 = _draw_portrait(**c4_params, shift_x=0, shift_y=0, brightness_delta=0, seed=401)

    # Invalid / No-Face image (Blurry background pattern for liveness rejection test)
    invalid_img = np.full((440, 400, 3), (120, 125, 130), dtype=np.uint8)
    cv2.putText(
        invalid_img,
        "NO FACE / OBSTRUCTED CAMERA",
        (35, 220),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (135, 140, 145),
        2,
    )

    samples = {
        "customer_01_checkin.jpg": img_c1_a,
        "customer_01_checkout.jpg": img_c1_b,
        "customer_02_checkin.jpg": img_c2_a,
        "customer_02_checkout.jpg": img_c2_b,
        "customer_03_checkin.jpg": img_c3_a,
        "customer_03_checkout.jpg": img_c3_b,
        "customer_04_stranger.jpg": img_c4,
        "invalid_no_face.jpg": invalid_img,
    }

    for fname, mat in samples.items():
        fpath = target_dir / fname
        cv2.imwrite(str(fpath), mat)
        paths[fname] = fpath

    return paths


if __name__ == "__main__":
    generated = generate_all_sample_faces()
    for k, v in generated.items():
        print(f"Generated: {k} -> {v}")
