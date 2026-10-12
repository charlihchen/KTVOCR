# KTVOCR
Karaoke music video OCR

## in English

There are 10,000 Karaoke music video filenames need to be renamed as singer-songName-language-songCategory...

By human, you have to open and play file one by one for 10,000 times to recognize the song as Chinese, Englsih, Japanese, or Korean etc. language, and then you will see the song title and the singer or group name, then regonize the song as fork, pop, or children song etc.

Write down as many as information from the song, and then close the video, then rename the file name to singer-songName-language-songCategory

   It is 10,000 songs, you will take time to rename files.
So, fopefully to write an APP to load or scan those files and do the video OCR to grap the singer name and song title.
Of cuse that capture the video audio to see what kind of language that it is singing? Chinese, Taiwanese, English, Korean, or Japanese etc.

| For part of file name | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| Language | English | Chinese | Japanese | Korean | Taiwanese | Cantonese |  
| Category | Male | Female | Group | Duet/Chorus |

### fielname sampler

- Madonna-Papa Don't Preach-英語-女歌星.mp4
- Kylie Minogue-I Should Be So Lucky-英語-外國女.mkv
- George Michael+Elton John-Don't Let The Sun Go Down On Me-英語-合唱.mkv
- ABBA-Dancing Queen(1976)-英語-外國團體.mkv
- Savage Garden-Truly Madly Deeply-英語-團體.mkv

## in Chinese

我有約一萬首卡拉OK的歌(445 GB)，但是它們的檔名都是數字而非"歌手-歌名"的檔名。
所以希望藉由???討論園地的大家之"人工"智慧力量來完成這一萬多首卡拉OK歌的檔名更名。
如此的檔名就更容易加歌到 CrazyKTV 卡拉OK點歌軟體 中。

Source: 
- [CrazyKTV 加歌程式](https://github.com/CrazyKTV/SongMgr)
- [CrazyKTV 電腦卡拉OK系統社團](https://www.facebook.com/groups/1915014728785932/)

我已初步瀏覽這些影片而將它們歸納到適當的檔案夾中， 
接下來就希望大家的分工來幫忙瀏覽影片來將它的檔名更名；然後上傳新檔名。
新檔名格式最好還保留原檔名的數字: 例如: 歌手-歌名(國語-男歌星-123456).mp4。
註解:
原來想說等AI技術成熟後;看看有沒有影片辨識來更檔名的程式；看來目前還是由大家的"人工"智慧力量來完成比較實際。
民謠檔案夾內的歌檔可以以後來再處理或不處理，因為這些歌對台灣來講比較不流行。

| 檔名的一部分 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| 語言 | 英語 | 國語 | 日語 | 韓語 | 台語 | 粵語 |  
| 分類 | 男生 | 女生 | 團體 | 合唱 |

### 檔名例子

- 林俊傑-江南(海蝶)-國語-男歌星.mkv
- 莫文蔚-這世界那麼多人(HD)-國語-女歌星.mp4
- 郭家瑋+DIOR大穎-過了幾天-國語-合唱.mkv
- 動力火車-忠孝東路走九遍-國語-團體.mkv

---

## KTV OCR Renamer App

See [`app/`](app/) for a tool that automates the renaming: it scans karaoke videos, uses OCR to read the song title and singer from the video frames, detects the sung language from the audio, and renames files to `singer-songName-language-songCategory`.

- **Web UI** — upload videos one by one, confirm the OCR guesses with one click, rename.
- **Batch mode** — `python batch.py scan <folder> -o guesses.csv`, review/edit the CSV, then `python batch.py apply guesses.csv --outdir renamed/`.

### App Web UI screenshot

<img width="624" height="885" alt="image" src="https://github.com/user-attachments/assets/1be84357-7ce1-4681-92a4-e1eb9f03f453" />
<img width="870" height="872" alt="image" src="https://github.com/user-attachments/assets/060d860e-b9e6-4986-8dd6-26a0c48b652c" />

