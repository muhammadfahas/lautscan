"""Download real authentic photographs for all 13 marine species and optimize them."""
import os
import io
import time
import urllib.request
import json
from PIL import Image

PHOTOS_FILES = {
    'thunnus_albacares': 'File:Thon Jaune.jpg',
    'thunnus_obesus': 'File:Thunnus obesus (bigeye tuna).jpg',
    'katsuwonus_pelamis': 'File:Katsuwonus pelamis Java.jpg',
    'euthynnus_affinis': 'File:Euthynnus affinis Maldives.JPG',
    'rastrelliger_kanagurta': 'File:Rastrelliger kanagurta JNC2855.JPG',
    'decapterus_russelli': 'File:Decapterus russelli India.jpg',
    'scomberomorus_commerson': 'File:Scomberomorus commerson Australia.jpg',
    'lutjanus_malabaricus': 'File:13-08-06-abu-dhabi-marina-mall-64.jpg',
    'epinephelus_coioides': 'File:Epinephelus coioides Thailand.jpg',
    'sardinella_lemuru': 'File:Kerala Sardine.jpg',
    'coryphaena_hippurus': 'File:Common Dolphinfish Monterey Bay.jpg',
    'cheilinus_undulatus': 'File:Cheilinus undulatus Maldives.JPG',
    'penaeus_monodon': 'File:Penaeus monodon.jpg'
}

out_dir = "web/assets/species"
os.makedirs(out_dir, exist_ok=True)

headers = {'User-Agent': 'LautScanMarineApp/1.0 (contact: info@lautscan.local)'}

for key, fname in PHOTOS_FILES.items():
    print(f"Resolving photo URL for {key} ({fname})...")
    api_url = f"https://commons.wikimedia.org/w/api.php?action=query&titles={urllib.parse.quote(fname)}&prop=imageinfo&iiprop=url&iiurlwidth=900&format=json"
    req = urllib.request.Request(api_url, headers=headers)
    img_url = None
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            pages = data.get('query', {}).get('pages', {})
            for pid, page in pages.items():
                info = page.get('imageinfo', [{}])[0]
                img_url = info.get('thumburl') or info.get('url')
    except Exception as e:
        print(f"Error resolving {key}: {e}")
        continue

    if not img_url:
        print(f"Failed to find URL for {key}")
        continue

    # Download image
    print(f"Downloading {key} from {img_url}...")
    try:
        img_req = urllib.request.Request(img_url, headers=headers)
        with urllib.request.urlopen(img_req, timeout=20) as resp:
            img_bytes = resp.read()

        im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        # Resize to max dimension 800 while maintaining aspect ratio
        target_w = 640
        aspect = im.height / im.width
        target_h = int(target_w * aspect)
        im_resized = im.resize((target_w, target_h), Image.Resampling.LANCZOS)

        out_path = os.path.join(out_dir, f"{key}.jpg")
        im_resized.save(out_path, "JPEG", quality=88, optimize=True)
        print(f"Successfully saved {out_path} ({im_resized.width}x{im_resized.height})")
    except Exception as e:
        print(f"Error downloading {key}: {e}")
    time.sleep(0.5)

print("All real fish photos processed.")
