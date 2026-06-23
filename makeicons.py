from PIL import Image, ImageDraw

for size in [192, 512]:
    img = Image.new('RGB', (size, size), '#7c3aed')
    draw = ImageDraw.Draw(img)
    draw.text((size//3, size//3), 'HS', fill='white')
    img.save(f'static/icon-{size}.png')

print('Icons created successfully')