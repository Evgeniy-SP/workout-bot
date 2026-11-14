"""Сервис для генерации графиков прогресса с помощью matplotlib."""
import io
import matplotlib

# ВАЖНО: Используем Agg бэкенд, чтобы рисовать без окна (для сервера)
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

import io
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta  # <--- Добавили timedelta


def generate_progress_chart(dates: list[datetime], values: list[float],
                            title: str, y_label: str) -> io.BytesIO:
    """Рисует график по датам и возвращает картинку в виде байтов."""
    plt.style.use('dark_background')

    fig, ax = plt.subplots(figsize=(8, 4), dpi=150)

    if len(dates) == 1:
        ax.plot(dates, values, marker='o', linestyle='', color='#00c9ff',
                markersize=12)
    else:
        ax.plot(dates, values, marker='o', linestyle='-', color='#00c9ff',
                linewidth=2, markersize=6)

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))

    # === УМНОЕ МАСШТАБИРОВАНИЕ ОСИ X ===
    if len(dates) == 1:
        # Если 1 точка: показываем окно в 2 дня (день до и день после)
        ax.set_xlim(dates[0] - timedelta(days=1), dates[0] + timedelta(days=1))
    else:
        # Если несколько точек: показываем от первой до последней + небольшой отступ по краям
        min_date = dates[0] - timedelta(days=1)
        max_date = dates[-1] + timedelta(days=1)
        ax.set_xlim(min_date, max_date)

        # Если точек мало (меньше 5), принудительно ставим метки на каждый день
        if len(dates) <= 5:
            ax.set_xticks(dates)
            ax.set_xticklabels([d.strftime('%d.%m') for d in dates])

    fig.autofmt_xdate()
    # ==================================

    ax.set_title(title, fontsize=14, color='white', pad=15)
    ax.set_ylabel(y_label, fontsize=12)
    ax.set_xlabel('Дата', fontsize=12)

    ax.grid(True, linestyle='--', alpha=0.3)

    for x, y in zip(dates, values):
        ax.annotate(f'{y:g}', (x, y), textcoords="offset points",
                    xytext=(0, 10), ha='center', fontsize=9)

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png', transparent=False, facecolor='#17212b')
    buf.seek(0)
    plt.close(fig)

    return buf
