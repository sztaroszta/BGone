"""
BGone

Description:
    BGone is a GUI-based Python utility designed to remove the background
    from a single image using a selection of popular AI-powered models. It
    provides a streamlined, user-friendly workflow for artists, designers,
    and developers to compare the output of different background removal
    libraries side-by-side.

Workflow:
    1.  The user is first prompted to select a local image file. The tool
        natively supports standard formats (PNG, JPEG) as well as the
        HEIC/HEIF format.
    2.  Next, a "Save As" dialog appears, allowing the user to choose a
        directory and a base filename for the output images.
    3.  A custom dialog is then displayed, listing all available background
        removal models. The user can select one or more models to process
        the image.
    4.  For each selected model, the script runs the background removal
        process. To improve performance on subsequent runs, initialized
        model sessions are cached in memory.
    5.  A transparent PNG file is saved for each successfully processed
        image. The output filename is constructed from the user-defined
        base name and a suffix identifying the model used (e.g.,
        `my_image_bgremoved_rembg_u2net.png`).
    6.  All operations, progress, and errors are logged to the console in
        real-time.

Usage:
    - Ensure all required libraries are installed by running the following
      command in your terminal:
          pip install pillow pillow-heif rembg transparent-background onnxruntime opencv-python mediapipe

    - Execute the script from the command line:
          python ai_bg_remover.py

Author:     Vitalii Starosta
GitHub:     https://github.com/sztaroszta
License:    MIT
"""
import os
import sys
import traceback
from datetime import datetime
from tkinter import (Button, Checkbutton, Frame, Label, Toplevel, Tk,
                     filedialog, BooleanVar, _tkinter)

from PIL import Image

# Attempt to register the HEIC/HEIF image format opener with Pillow.
# This requires the `pillow-heif` library to be installed.
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    print("Warning: The 'pillow-heif' library is not installed.")
    print("HEIC/HEIF image format support will be disabled.")
    print("To enable it, run: pip install pillow-heif")


# Attempt to import computer vision libraries required for MediaPipe.
# Provide guidance if they are not installed.
try:
    import cv2
    import mediapipe as mp
    import numpy as np
except ImportError:
    print("One or more required libraries (opencv-python, numpy, mediapipe) are not installed.")
    print("Please run: pip install opencv-python numpy mediapipe")
    # Allow the script to continue, as other models may still function.


# --- MODEL AND PROCESSOR CONFIGURATION ---
MODELS_CONFIG = {
    "rembg_u2net": {"display_name": "Rembg (U2Net - General Purpose)", "processor": "rembg_base", "params": {"model_name": "u2net"}},
    "rembg_u2netp": {"display_name": "Rembg (U2Netp - Lightweight)", "processor": "rembg_base", "params": {"model_name": "u2netp"}},
    "rembg_silueta": {"display_name": "Rembg (Silueta)", "processor": "rembg_base", "params": {"model_name": "silueta"}},
    "rembg_isnet_general": {"display_name": "Rembg (IS-Net General Use)", "processor": "rembg_base", "params": {"model_name": "isnet-general-use"}},
    "rembg_isnet_anime": {"display_name": "Rembg (IS-Net Anime - For Drawings)", "processor": "rembg_base", "params": {"model_name": "isnet-anime"}},
    "rembg_sam": {"display_name": "Rembg (SAM - High Detail, Slow)", "processor": "rembg_base", "params": {"model_name": "sam"}},
    "transparent_background_base": {"display_name": "Transparent Background (Base - Slower, Accurate)", "processor": "transparent_bg", "params": {"mode": "base", "type": "rgba"}},
    "transparent_background_fast": {"display_name": "Transparent Background (Fast)", "processor": "transparent_bg", "params": {"mode": "fast", "type": "rgba"}},
    "mediapipe_selfie": {"display_name": "MediaPipe (Selfie/Person - Very Fast)", "processor": "mediapipe_person", "params": {}}
}
_rembg_sessions = {}
_transparent_bg_removers = {}
_mediapipe_segmenter = None


# --- BACKGROUND REMOVAL PROCESSORS ---
def process_with_rembg(image_pil, model_name="u2net"):
    from rembg import new_session, remove
    if model_name not in _rembg_sessions:
        try:
            log_message(f"Initializing rembg session for model: {model_name}")
            _rembg_sessions[model_name] = new_session(model_name=model_name)
        except Exception as e:
            log_message(f"Error initializing rembg session for {model_name}: {e}")
            log_message("Ensure 'rembg' is installed and you have an internet connection for model download.")
            return None
    return remove(image_pil, session=_rembg_sessions[model_name])

def process_with_transparent_background(image_pil, mode="base", type="rgba"):
    from transparent_background import Remover as TBR_Remover
    image_rgb = image_pil.convert("RGB")
    cache_key = f"{mode}"
    if cache_key not in _transparent_bg_removers:
        try:
            log_message(f"Initializing transparent-background remover (mode: {mode})")
            _transparent_bg_removers[cache_key] = TBR_Remover(mode=mode)
        except Exception as e:
            log_message(f"Error initializing transparent-background (mode: {mode}): {e}")
            log_message("Make sure 'transparent-background' and 'onnxruntime' are installed.")
            return None
    return _transparent_bg_removers[cache_key].process(image_rgb, type=type)

def process_with_mediapipe(image_pil, **kwargs):
    global _mediapipe_segmenter
    if 'mp' not in sys.modules:
        log_message("MediaPipe library not found. Skipping.")
        return None
    if _mediapipe_segmenter is None:
        log_message("Initializing MediaPipe Selfie Segmentation...")
        SelfieSegmentation = mp.solutions.selfie_segmentation.SelfieSegmentation
        _mediapipe_segmenter = SelfieSegmentation(model_selection=0)
        log_message("MediaPipe Initialized.")
    image_np = np.array(image_pil.convert('RGB'))
    image_np_bgr = cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)
    results = _mediapipe_segmenter.process(image_np_bgr)
    mask = results.segmentation_mask
    if mask is None:
        log_message("MediaPipe did not detect a person. Returning original image.")
        return image_pil
    condition = np.stack((mask,) * 3, axis=-1) > 0.1
    output_image_bgr = np.where(condition, image_np_bgr, np.zeros_like(image_np_bgr))
    alpha_channel = (mask * 255).astype(np.uint8)
    output_image_bgra = np.concatenate([output_image_bgr, alpha_channel[..., np.newaxis]], axis=-1)
    output_image_rgba = cv2.cvtColor(output_image_bgra, cv2.COLOR_BGRA2RGBA)
    return Image.fromarray(output_image_rgba)

PROCESSOR_FUNCTIONS = {"rembg_base": process_with_rembg, "transparent_bg": process_with_transparent_background, "mediapipe_person": process_with_mediapipe}


# --- UTILITY AND GUI HELPER FUNCTIONS ---
def log_message(message):
    print(message)

def get_input_file_path():
    filetypes_list = [("All supported images", "*.jpg *.jpeg *.png *.bmp *.gif *.tiff *.heic *.heif"), ("HEIC/HEIF files", "*.heic *.heif"), ("Image files", "*.jpg *.jpeg *.png *.bmp *.gif *.tiff"), ("All files", "*.*")]
    return filedialog.askopenfilename(title="Select Input Image", filetypes=tuple(filetypes_list))

def get_base_output_path(input_filename=""):
    default_filename = ""
    if input_filename:
        input_stem = os.path.splitext(os.path.basename(input_filename))[0]
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        default_filename = f"{input_stem}_bgremoved_{timestamp}"
    return filedialog.asksaveasfilename(title="Choose Base Name and Location for Output(s)", initialfile=default_filename, defaultextension=".png", filetypes=(("PNG files", "*.png"), ("All files", "*.*")))

def ask_model_selection():
    dialog = Toplevel()
    dialog.title("Choose Background Removal Model(s)")
    dialog.attributes('-topmost', True)
    selections = {}
    Label(dialog, text="Select one or more models to use:").pack(pady=10, padx=10)
    options_frame = Frame(dialog)
    options_frame.pack(pady=5, padx=10, fill="x")
    for key, config in MODELS_CONFIG.items():
        var = BooleanVar(value=False)
        cb = Checkbutton(options_frame, text=config["display_name"], variable=var)
        cb.pack(anchor="w")
        selections[key] = var
    def select_all(): [var.set(True) for var in selections.values()]
    def deselect_all(): [var.set(False) for var in selections.values()]
    btn_frame = Frame(dialog)
    btn_frame.pack(pady=(5, 10), padx=10, fill="x")
    Button(btn_frame, text="Select All", command=select_all).pack(side="left", expand=True, padx=5)
    Button(btn_frame, text="Deselect All", command=deselect_all).pack(side="left", expand=True, padx=5)
    chosen_models = []
    def on_ok():
        nonlocal chosen_models
        chosen_models = [key for key, var in selections.items() if var.get()]
        if not chosen_models: log_message("Warning: No models were selected.")
        dialog.destroy()
    def on_cancel():
        nonlocal chosen_models
        chosen_models = []
        dialog.destroy()
    action_frame = Frame(dialog)
    action_frame.pack(pady=10, padx=10, fill="x")
    Button(action_frame, text="Process", command=on_ok).pack(side="left", expand=True, padx=5)
    Button(action_frame, text="Cancel", command=on_cancel).pack(side="right", expand=True, padx=5)
    dialog.transient()
    dialog.grab_set()
    dialog.wait_window()
    return chosen_models


# --- MAIN APPLICATION LOGIC ---
def main():
    root = None
    try:
        # Attempt to create the main Tkinter window.
        root = Tk()
        root.withdraw()
        root.attributes('-topmost', True)
    except _tkinter.TclError as e:
        # Handle the case where a display is not available.
        if "no display name" in str(e):
            log_message("="*50)
            log_message("This is a GUI application, but it is running in a")
            log_message("non-graphical environment. The program will exit gracefully.")
            log_message("To run BGone, please execute the script in a")
            log_message("desktop environment that supports graphical displays.")
            log_message("="*50)
            return  # Exit the application cleanly.
        else:
            # Re-raise any other Tkinter errors.
            raise

    try:
        input_path = get_input_file_path()
        if not input_path:
            log_message("No input file selected. Exiting.")
            return

        log_message(f"Input file: {input_path}")
        base_output_path = get_base_output_path(input_path)
        if not base_output_path:
            log_message("No output location selected. Exiting.")
            return

        selected_model_keys = ask_model_selection()
        if not selected_model_keys:
            log_message("No models selected. Exiting.")
            return

        # --- Image Loading & Processing ---
        try:
            log_message(f"Loading input image: {input_path}")
            input_image_pil = Image.open(input_path)
            if input_image_pil.mode != 'RGBA':
                input_image_pil = input_image_pil.convert('RGBA')
        except Exception as e:
            log_message(f"Error opening input image: {e}")
            return

        output_dir = os.path.dirname(base_output_path)
        base_filename, _ = os.path.splitext(os.path.basename(base_output_path))
        for model_key in selected_model_keys:
            config = MODELS_CONFIG.get(model_key)
            if not config:
                log_message(f"Unknown model key: '{model_key}'. Skipping.")
                continue
            
            output_filename = f"{base_filename}_{model_key}.png"
            current_output_path = os.path.join(output_dir, output_filename)
            log_message(f"\nProcessing with: {config['display_name']}...")
            try:
                processor_function = PROCESSOR_FUNCTIONS[config["processor"]]
                output_image_pil = processor_function(input_image_pil.copy(), **config["params"])
                if output_image_pil:
                    output_image_pil.save(current_output_path)
                    log_message(f"Successfully saved output to: {current_output_path}")
                else:
                    log_message(f"Failed to process with {config['display_name']}.")
            except Exception as e:
                log_message(f"An unexpected error occurred with {config['display_name']}: {e}")
                log_message(traceback.format_exc())

        log_message("\n--- All selected processing tasks are complete. ---")
    finally:
        # Ensure the root window is destroyed if it was created.
        if root:
            root.destroy()

# --- SCRIPT ENTRY POINT ---
if __name__ == "__main__":
    print("=" * 40)
    print("BGone")
    print("=" * 40)
    main()
    print("\n--- Script finished. ---")