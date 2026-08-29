# 🇹🇷 Stremio Türkçe Dublaj & Altyazı Eklentisi (Addon)

Stremio için **Türkçe Dublaj**, **Türkçe Altyazı** ve **Dual Audio** kaynaklarını (hem doğrudan hızlı web video oynatıcıları hem de yüksek kaliteli torrentler) tek çatı altında toplayan eklenti.

---

## ✨ Özellikler

- 🔊 **Türkçe Dublaj & Dual Audio:** Torrentio'da bulunmayan yerli dublaj ve ses kanallarını otomatik tespit eder.
- ⚡ **Direkt Hızlı Akışlar:** Torrent beklemeden saniyeler içinde açılan HLS / MP4 video akışları (HDFilmcehennemi, Dizipal, FullHDFilmizlesene, Diziwatch vb.).
- 🧲 **Türkçe Torrent Kaynakları:** Yüksek bitrate ve 1080p/4K Dual Audio torrent kaynakları.
- 📺 **TV ve PC Senkronizasyonu:** Stremio hesabınıza eklentiyi bir kez eklediğinizde; Android TV, Google TV, Samsung Tizen, LG WebOS, Apple TV, PC ve Telefonunuzda otomatik olarak senkronize olur.
- 🛡️ **Akıllı Yayın Proxy'si:** TV cihazlarında veya tarayıcılarda oluşan CORS / Referer kısıtlamalarını aşmak için yerleşik akıllı proxy motoru.
- 🎨 **Modern Yapılandırma Paneli:** Kaynakları ve kalite filtrelerini özelleştirebileceğiniz şık web arayüzü ve QR kod desteği.

---

## 🚀 Hızlı Başlangıç (Yerel Çalıştırma)

1. Gerekli kütüphaneleri yükleyin (zaten yüklendiyse bu adımı atlayabilirsiniz):
   ```bash
   pip install -r requirements.txt
   ```

2. Eklentiyi başlatın:
   - Windows'ta `start.bat` dosyasına çift tıklayın veya:
   ```bash
   python run.py
   ```

3. Tarayıcınızda açın:
   - **Yapılandırma & Kurulum Paneli:** [http://localhost:7000](http://localhost:7000)
   - **Manifest Linki:** `http://localhost:7000/manifest.json`

4. **Stremio'ya Ekleme:**
   - Web arayüzündeki **"Stremio'ya Yükle"** butonuna tıklayın veya Stremio Addons arama çubuğuna manifest linkini yapıştırın.

---

## 📺 TV ve PC Arasında Senkronizasyon

Stremio'nun bulut hesap mimarisi sayesinde:
1. Bilgisayarınızda veya telefonunuzda **[stremio.com](https://web.stremio.com)** veya Stremio uygulamasını açıp hesabınıza giriş yapın.
2. Eklentiyi hesabınıza kurun (`Stremio'ya Yükle` butonuna basarak).
3. Televizyonunuzdaki Stremio uygulamasını açtığınızda eklenti **otomatik olarak TV'nize gelir**; TV'den ayrıca bir ayar yapmanıza gerek kalmaz.

---

## ☁️ 7/24 Bulut Sunucuya Yükleme (Ücretsiz)

Bilgisayarınızı sürekli açık tutmak istemiyorsanız, eklentiyi ücretsiz bulut servislerine yükleyebilirsiniz:

### 1. Render.com ile Dağıtım (Önerilen)
1. Bu projeyi bir GitHub reposuna yükleyin.
2. [Render.com](https://render.com) üzerinde **New Web Service** seçin.
3. Reponuzu bağlayın, ortam olarak `Python 3` ve Start Command olarak `python run.py` yazın.
4. Size verilen `https://proje-adiniz.onrender.com/manifest.json` linkini Stremio'ya ekleyin!

### 2. Docker ile Çalıştırma
```bash
docker build -t stremio-turkish-addon .
docker run -d -p 7000:7000 --name stremio-tr stremio-turkish-addon
```
