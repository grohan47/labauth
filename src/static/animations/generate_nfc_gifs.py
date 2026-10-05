import math
from PIL import Image, ImageDraw

def render_frame(mode, frame_idx, total_frames=36, size=360):
    # 2x supersampling for ultra-crisp antialiasing
    scale = 2
    W = size * scale
    H = size * scale
    
    is_dark = (mode == "dark")
    # Exact background match with --sbb-color-midnight (#151515) and --sbb-color-milk (#f6f6f6)
    bg_color = (21, 21, 21, 255) if is_dark else (246, 246, 246, 255)
    red_color = (235, 0, 0, 255)
    
    img = Image.new("RGBA", (W, H), bg_color)
    draw = ImageDraw.Draw(img)
    
    t = frame_idx / total_frames
    
    # Motion curve for card tap:
    # 0.00 -> 0.35: smooth descent towards rectangular reader
    # 0.35 -> 0.52: tap contact / hold on reader
    # 0.52 -> 1.00: smooth lift back to floating position
    if t < 0.35:
        p = t / 0.35
        pos_factor = p * p  # ease-in
        pulse_active = False
    elif t < 0.52:
        pos_factor = 1.0
        pulse_active = True
    else:
        p = (t - 0.52) / 0.48
        pos_factor = 1.0 - math.sin(p * math.pi * 0.5)  # ease-out
        pulse_active = False

    # -------------------------------------------------------------------------
    # 1. Sleek Rectangular NFC Reader Terminal
    # -------------------------------------------------------------------------
    rx = W // 2
    ry = int(H * 0.60)
    rw = int(184 * scale)
    rh = int(132 * scale)
    radius = int(14 * scale)
    
    rect_box = [rx - rw // 2, ry - rh // 2, rx + rw // 2, ry + rh // 2]
    
    # Reader base fill
    reader_fill = (26, 26, 32, 255) if is_dark else (255, 255, 255, 255)
    
    # Border: Crisp SBB Red outline (illuminates brighter when tapped)
    border_color = (235, 0, 0, 255) if pulse_active else ((235, 0, 0, 200) if is_dark else (235, 0, 0, 210))
    border_width = int(4 * scale) if pulse_active else int(3 * scale)
    
    # Subtle reader shadow
    if is_dark:
        shadow_box = [rect_box[0] - int(2*scale), rect_box[1] + int(2*scale), rect_box[2] + int(2*scale), rect_box[3] + int(6*scale)]
        draw.rounded_rectangle(shadow_box, radius=radius, fill=(12, 12, 14, 180))
    else:
        shadow_box = [rect_box[0] - int(1*scale), rect_box[1] + int(3*scale), rect_box[2] + int(1*scale), rect_box[3] + int(7*scale)]
        draw.rounded_rectangle(shadow_box, radius=radius, fill=(210, 210, 220, 140))
        
    draw.rounded_rectangle(rect_box, radius=radius, fill=reader_fill, outline=border_color, width=border_width)
    
    # Inner accent bevel / border inside the rectangular reader
    inner_pad = int(8 * scale)
    inner_box = [rect_box[0] + inner_pad, rect_box[1] + inner_pad, rect_box[2] - inner_pad, rect_box[3] - inner_pad]
    inner_color = (48, 48, 58, 255) if is_dark else (232, 232, 240, 255)
    draw.rounded_rectangle(inner_box, radius=max(2, radius - inner_pad // 2), outline=inner_color, width=int(1.5 * scale))

    # Top Status LED pill
    led_w = int(14 * scale)
    led_h = int(4 * scale)
    led_x = rx
    led_y = rect_box[1] + int(12 * scale)
    led_col = red_color if pulse_active else ((90, 90, 105, 255) if is_dark else (175, 175, 190, 255))
    draw.rounded_rectangle([led_x - led_w // 2, led_y - led_h // 2, led_x + led_w // 2, led_y + led_h // 2], radius=int(2*scale), fill=led_col)

    # -------------------------------------------------------------------------
    # Contactless NFC Wave Logo in Reader Center (((•)))
    # -------------------------------------------------------------------------
    nfc_cx = rx - int(16 * scale)
    nfc_cy = ry + int(4 * scale)
    nfc_col = red_color
    
    # 4 curved radiating waves
    wave_radii = [int(11 * scale), int(21 * scale), int(31 * scale), int(41 * scale)]
    for r in wave_radii:
        bbox = [nfc_cx - r, nfc_cy - r, nfc_cx + r, nfc_cy + r]
        draw.arc(bbox, start=-46, end=46, fill=nfc_col, width=int(3.5 * scale))
        
    # Origin dot / beacon
    draw.ellipse([nfc_cx - int(3.5*scale), nfc_cy - int(3.5*scale), nfc_cx + int(3.5*scale), nfc_cy + int(3.5*scale)], fill=nfc_col)

    # -------------------------------------------------------------------------
    # 2. Transit / Identity Card
    # -------------------------------------------------------------------------
    card_w = int(164 * scale)
    card_h = int(104 * scale)
    
    start_y = int(H * 0.22)
    target_y = int(ry - card_h * 0.40)
    card_cy = int(start_y + (target_y - start_y) * pos_factor)
    
    start_x = int(W * 0.53)
    target_x = int(W * 0.50)
    card_cx = int(start_x + (target_x - start_x) * pos_factor)
    
    angle = -11.0 * (1.0 - pos_factor)
    
    # Render card onto high-res sublayer for clean rotation and drop-shadow
    sub_w = card_w + int(50 * scale)
    sub_h = card_h + int(50 * scale)
    card_img = Image.new("RGBA", (sub_w, sub_h), (0, 0, 0, 0))
    cdraw = ImageDraw.Draw(card_img)
    
    pad = int(25 * scale)
    x0, y0 = pad, pad
    x1, y1 = pad + card_w, pad + card_h
    corner_r = int(9 * scale)
    
    # Drop shadow below the card
    shadow_offset = int((8 - 4 * pos_factor) * scale)
    shadow_alpha = int((120 + 70 * pos_factor))
    shadow_col = (0, 0, 0, shadow_alpha)
    cdraw.rounded_rectangle([x0, y0 + shadow_offset, x1, y1 + shadow_offset], radius=corner_r, fill=shadow_col)
    
    card_bg = (34, 34, 42, 255) if is_dark else (255, 255, 255, 255)
    card_stroke = (235, 0, 0, 255)
    
    # Card base
    cdraw.rounded_rectangle([x0, y0, x1, y1], radius=corner_r, fill=card_bg, outline=card_stroke, width=int(2.5 * scale))
    
    # SBB Red Header Stripe across top of card
    stripe_h = int(22 * scale)
    cdraw.rounded_rectangle([x0, y0, x1, y0 + stripe_h], radius=corner_r, fill=red_color)
    cdraw.rectangle([x0, y0 + corner_r, x1, y0 + stripe_h], fill=red_color)
    
    # Swiss Cross on stripe
    cross_cx = x0 + int(22 * scale)
    cross_cy = y0 + stripe_h // 2
    cw = int(14 * scale)
    ch = int(5 * scale)
    cdraw.rectangle([cross_cx - cw//2, cross_cy - ch//2, cross_cx + cw//2, cross_cy + ch//2], fill=(255, 255, 255, 255))
    cdraw.rectangle([cross_cx - ch//2, cross_cy - cw//2, cross_cx + ch//2, cross_cy + cw//2], fill=(255, 255, 255, 255))
    
    # "LabAuth" badge mockup line
    cdraw.rectangle([cross_cx + int(14 * scale), cross_cy - int(3 * scale), cross_cx + int(48 * scale), cross_cy + int(3 * scale)], fill=(255, 255, 255, 255))
    
    # Smart Chip icon on card
    chip_x = x0 + int(22 * scale)
    chip_y = y0 + int(38 * scale)
    chip_w = int(22 * scale)
    chip_h = int(19 * scale)
    chip_col = (205, 165, 45, 255)
    cdraw.rounded_rectangle([chip_x, chip_y, chip_x + chip_w, chip_y + chip_h], radius=int(3*scale), fill=chip_col)
    cdraw.line([chip_x + chip_w//2, chip_y, chip_x + chip_w//2, chip_y + chip_h], fill=(160, 120, 20, 255), width=int(1*scale))
    cdraw.line([chip_x, chip_y + chip_h//2, chip_x + chip_w, chip_y + chip_h//2], fill=(160, 120, 20, 255), width=int(1*scale))
    
    # Contactless wave symbol on card
    cw_x = x1 - int(30 * scale)
    cw_y = y0 + int(46 * scale)
    for i in range(3):
        ar = int((7 + i * 5.5) * scale)
        cdraw.arc([cw_x - ar, cw_y - ar, cw_x + ar, cw_y + ar], start=-45, end=45, fill=red_color, width=int(2*scale))
        
    # Cardholder name mock lines
    line_col = (180, 180, 195, 255) if is_dark else (95, 95, 110, 255)
    cdraw.rectangle([x0 + int(18 * scale), y1 - int(24 * scale), x0 + int(88 * scale), y1 - int(18 * scale)], fill=line_col)
    cdraw.rectangle([x0 + int(18 * scale), y1 - int(14 * scale), x0 + int(56 * scale), y1 - int(10 * scale)], fill=(130, 130, 145, 255))
    
    # Rotate card smoothly
    rotated_card = card_img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    
    # Paste card onto main canvas centered at (card_cx, card_cy)
    paste_x = card_cx - rotated_card.width // 2
    paste_y = card_cy - rotated_card.height // 2
    img.alpha_composite(rotated_card, (paste_x, paste_y))
    
    # Downsample with Lanczos filter to target size (antialiased)
    final_frame = img.resize((size, size), Image.Resampling.LANCZOS)
    return final_frame.convert("RGB")

def make_gif(mode, output_path):
    frames = []
    total = 36
    for i in range(total):
        frames.append(render_frame(mode, i, total_frames=total, size=360))
    
    # Save as animated GIF: 33ms per frame = 30 fps
    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        duration=33,
        loop=0,
        optimize=True
    )
    print(f"Generated {output_path} successfully ({len(frames)} frames).")

if __name__ == "__main__":
    make_gif("dark", "src/static/animations/nfc-tap-dark.gif")
    make_gif("light", "src/static/animations/nfc-tap-light.gif")
