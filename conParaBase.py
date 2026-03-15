import base64

with open("known_faces/008268667BE047.jpg", "rb") as img:
    b64 = base64.b64encode(img.read()).decode()
    print("data:image/jpeg;base64," + b64)
