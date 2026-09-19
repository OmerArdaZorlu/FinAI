# HANDOFF — 2026-09-19 (ikinci oturum sonu)

Yeni oturum için durum özeti. Kalıcı kurallar `CLAUDE.md`'de; önce onu, sonra
bunu, sonra `docs/TECH_DEBT.md`'yi oku.

## Kullanıcıyla çalışma

- Sade Türkçe, jargonsuz, kısa. Soru sorulunca cevap ver, kod yazmaya başlama.
- **Anlatım dersi:** "koruma açıkları" iki kez tablo/terimle anlatıldı, anlaşılmadı.
  Üçüncüsünde işe yarayan: önce temel (Alpaca'da ne duruyor, ne gönderiyoruz,
  ne çekiyoruz), sonra **tek işlemin saat saat zaman çizelgesi**, sonra her
  açık o çizelgeye bağlanarak 2-3 cümle.
- Kullanıcı önerileri bu oturumda uygulandı: dakika başı kontrol, uyarı tablosu.

## Sistem (kısaca)

KABUL-1: AAPL saatlik, Donchian 140 bar. Alış `dip + 0.10×genişlik`, zarar
stopu `dip − 2.00×genişlik`, tepeye değince takip eden stop
`zirve − 1.00×genişlik`. Tek pozisyon, tam hisse, Alpaca **paper**.

## Bu oturumda yapılanlar (HEPSİ UNCOMMITTED — commit'i kullanıcı yapar)

Dört koruma açığı kapandı (pozisyon açıkken hisselerin tabansız kalması):

| açık | çözüm | yer |
|---|---|---|
| 1. Kısmi dolum → broker 100, kayıt 0 → motor durur | bitmiş emirde `filled_qty > 0` gerçek dolum; kısmen dolmuş alışın kalanı iptal, ≤10 sn beklenir | `motor._emirleri_isle`, `_kismi_alislari_sonlandir` |
| 2. Taban her saat iptal + yeniden | aynıysa dokunma, farklıysa **PATCH** ile yerinde güncelle | `broker.emri_guncelle`, `motor._emirleri_koy` |
| 3. Dolumla taban arası ≤1 saat boşluk | **koruma bekçisi** dakikada bir (borsa açık + pozisyon/bekleyen alış varken) | `motor.koruma_turu`, `dongu.py` |
| 4. Bölünme depoyu bozar | depo günde bir tam yenilenir; iki bar arası >%25 sıçramada hemen yenile, düzelmezse emir yok | `senkron.tazele(tam_yenileme_saat)`, `motor._sicrama` |

Ek olarak:
- **Uyarı tablosu** (`paper.db → uyarilar`): bekçi müdahaleleri, kısmi dolum,
  mutabakat, sıçrama, tüm sorun alarmları. E-posta ayarsız/susturulmuşken de yazılır;
  aynı uyarı 6 saat içinde tekrar ederse sayaç artar. Panelde "Uyarılar" bölümü, terminalde `/uyarilar`.
- İptal ile dolum yarışı: iptal edilen emrin akıbeti artık broker'dan okunuyor (dolum kaybolmuyor).
- Broker 403 mesajı Alpaca'nın gövdesini gösteriyor (yetersiz alım gücü / wash trade 403 döner).
- Bekçi mutabakat bozuksa **emirlere dokunmaz** (bölünmede eski seviyeye taban hisseleri sattırırdı).
- `scripts/parite.py` (ağa çıkmaz), `CLAUDE.md`, TECH_DEBT (TD-06/07/19 notları, **TD-21 ölçümle kapandı**), README.

**Plandan sapma:** bölünme eşiği "kanal genişliği > fiyatın %50'si" yerine
"iki bar arası sıçrama > %25". Sebep ölçüm: kanal mart 2020'de %42'ye çıkmış
(eşiğe çok yakın), en büyük bar-arası sıçrama ise %13,6.

**Doğrulama:** 259 test yeşil · parite 9.9004 / 28, parmak izi `d1e6ef7289d0e7f5` ·
kuru döngü gerçek ortamda açıldı (borsa kapalı, bekçi boşta sessiz) · panel geniş ve 504 px'te görüntülendi.

Önceki oturumlardan da uncommitted: senkron/kasa/tekrar/gunluk/dongu/saglik/alarm/arayüz,
`hypotheses/KABUL-1_*.md`, `hypotheses/gorseller/`, `scripts/kabul1_gorsel.py`.

## SIRADAKİ İŞ — Pazartesi canlı UI testi (borsa 16:30 TR'de açılır)

1. `.env`: `ARAYUZ_ANAHTARI` (telefon için), isteğe bağlı `SMTP_KULLANICI`, `SMTP_SIFRE` (Gmail uygulama parolası), `ALARM_ALICI`.
2. `python -m src.engine.dongu` + `python -m src.arayuz`.
3. İlk tur 16:20 TR (13:20 UTC) sonrası: panelde alış seviyesi, `/durum`'da alış emri bekliyor.
4. Alış dolunca **1 dakika içinde**: Uyarılar'da "Alış gerçekleşti — N hisseye taban konuldu", `/durum` → koruyucu stop borsada.
5. Kısmi dolum görülürse: Uyarılar'da "bir kısmı gerçekleşti", pozisyon adedi = broker adedi, taban o adet kadar.
6. Sonraki turlar: seviye değişmediyse günlükte iptal/yeni emir yok ("emir zaten yerinde"); takip stop yükselince "GÜNCELLENDİ".
7. `/duraklat` → bekleyen alış iptal; `/devam`.
8. Pozisyon açıkken `/stop onayla` → 5 sn içinde pozisyon kapanır (TD-09 tatbikatı), sonra `/sifirla onayla`.

**Canlıda ilk kez görülecek, izlenmeli:** PATCH'in Alpaca'daki gerçek davranışı
(yeni kimlik, eski emir `replaced`), kısmi dolumda iptal süresi, wash trade reddi olup olmadığı.

## Açık kararlar (hâlâ verilmedi)

Kasa (2024-07 →) açılsın mı · paper koşusu bitiş kriteri · eşik yenileme kuralı ·
REGISTRY borcu (~6 deney kaydedilmedi, deneme sayacı güncel değil — TD-14) ·
TD-09 kalanı (günlük zarar / maruziyet / emir-oranı limitleri).
