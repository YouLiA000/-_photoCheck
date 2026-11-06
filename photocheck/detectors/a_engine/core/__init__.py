"""PhotoCheck core package.

Ownership: A owns `core/detect` (detector engine), B owns load / redact /
verify / export, C owns dataset / evaluation / UI.

Importing this package must NOT pull in heavy dependencies. numpy, cv2,
rapidocr and mediapipe are all imported lazily inside functions, so C's eval
script and the unit tests run on machines without the models, and Gradio startup
does not block on model loading.
"""

__all__: list[str] = []
