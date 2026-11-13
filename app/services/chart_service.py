"""Сервис для генерации графиков прогресса с помощью matplotlib."""
import io
import matplotlib

# ВАЖНО: Используем Agg бэкенд, чтобы рисовать без окна (для сервера)
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime


def generate_progress_chart(dates: list[datetime], weights: list[float],
                            exercise_name: str) -> io.BytesIO:
    """
    Рисует линейный график веса по датам и возвращает картинку в виде байтов.
    """
    # Настраиваем стиль (темный, как в Telegram)
    plt.style.use('dark_background')

    fig, ax = plt.subplots(figsize=(8, 4), dpi=150)

    # Рисуем линию и точки
    ax.plot(dates, weights, marker='o', linestyle='-', color='#00c9ff',
            linewidth=2, markersize=6)

    # Красиво форматируем даты по оси X
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
    fig.autofmt_xdate()

    # Заголовки
    ax.set_title(f'Прогресс: {exercise_name}', fontsize=14, color='white',
                 pad=15)
    ax.set_ylabel('Вес (кг)', fontsize=12)
    ax.set_xlabel('Дата', fontsize=12)

    # Добавляем сетку
    ax.grid(True, linestyle='--', alpha=0.3)

    # Подписываем точки значениями
    for x, y in zip(dates, weights):
        ax.annotate(f'{y:g}', (x, y), textcoords="offset points",
                    xytext=(0, 10), ha='center', fontsize=9)

    plt.tight_layout()

    # Сохраняем в память
    buf = io.BytesIO()
    plt.savefig(buf, format='png', transparent=False,
                facecolor='#17212b')  # Цвет фона как у Telegram
    buf.seek(0)
    plt.close(fig)  # Обязательно закрываем фигуру, чтобы не жрало память

    return buf