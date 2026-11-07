import xml.etree.ElementTree as ET
from pybadges import badge

# Читаем отчет о покрытии
tree = ET.parse('coverage.xml')
root = tree.getroot()
line_rate = float(root.attrib['line-rate'])
percent = round(line_rate * 100)

# Генерируем SVG-бейдж
svg = badge(left_text='coverage', right_text=f'{percent}%', right_color='green')

# Сохраняем в файл
with open('coverage.svg', 'w') as f:
    f.write(svg)

print(f"✅ Бейдж создан: {percent}%")
