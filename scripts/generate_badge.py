import xml.etree.ElementTree as ET


def create_badge(percent):
    # Выбираем цвет в зависимости от процента
    if percent >= 80:
        color = "#4c1"  # Зеленый
    elif percent >= 50:
        color = "#dfb317"  # Желтый
    else:
        color = "#e05d44"  # Красный

    # Возвращаем SVG-код (стандартный бейдж shields.io)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="100" height="20">
  <linearGradient id="b" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <mask id="a">
    <rect width="100" height="20" rx="3" fill="#fff"/>
  </mask>
  <g mask="url(#a)">
    <path fill="#555" d="M0 0h60v20H0z"/>
    <path fill="{color}" d="M60 0h40v20H60z"/>
    <path fill="url(#b)" d="M0 0h100v20H0z"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
    <text x="30" y="15" fill="#010101" fill-opacity=".3">coverage</text>
    <text x="30" y="14">coverage</text>
    <text x="80" y="15" fill="#010101" fill-opacity=".3">{percent}%</text>
    <text x="80" y="14">{percent}%</text>
  </g>
</svg>'''

# Читаем отчет о покрытии
tree = ET.parse('coverage.xml')
root = tree.getroot()
percent = round(float(root.attrib['line-rate']) * 100)

# Сохраняем в файл
with open('coverage.svg', 'w') as f:
    f.write(create_badge(percent))

print(f"✅ Бейдж создан: {percent}%")
