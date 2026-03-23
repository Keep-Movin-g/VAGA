import paddle
print("Paddle Path:", paddle.__file__) # 看看它加载的是不是你截图里的那个
print("GPU Support:", paddle.device.is_compiled_with_cuda())
print("Device Name:", paddle.device.get_device())

from paddleocr import PaddleOCR
ocr = PaddleOCR(use_angle_cls=True, lang="ch", use_gpu=True)
print("OCR Loaded Successfully")