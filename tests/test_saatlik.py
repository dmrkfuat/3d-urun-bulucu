from datetime import datetime, timezone

from urun_bulucu import saatlik


def test_mesaj_son_ozetle():
    secimler = [{"rank": i, "score": 90 - i, "product_id": i,
                 "products": {"name": f"Model <{i}>", "url": f"https://makerworld.com/en/models/{i}",
                              "cost_tl": 20.6, "price_tl": 65, "trend_rank": 2 if i == 1 else None}}
                for i in range(1, 8)]
    m = saatlik.mesaj("2026-11-09", secimler, "https://panel.example",
                      datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc))
    assert m.startswith("🧪 <b>Saatlik test</b> — 09.11.2026 21:00")   # Türkiye saati
    assert "Son özet: <b>2026-11-09</b>" in m
    assert "1. <a href=\"https://makerworld.com/en/models/1\">Model &lt;1&gt;</a> — 89🔥 · 21→65 TL" in m
    assert "5. <a" in m and "6. <a" not in m                    # en fazla 5 ürün
    assert m.endswith("📊 Panel: https://panel.example")


def test_mesaj_ozet_yokken():
    m = saatlik.mesaj(None, [], None, datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc))
    assert "Henüz kayıtlı özet yok." in m and "Panel" not in m
