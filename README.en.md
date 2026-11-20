# PromptShop

[日本語](README.md) | **English**

PromptShop is a tool that runs entirely on your own PC. You save prompts for image transformation (filters, art-style conversion and so on), apply them to a source image, and compare the results.

- Save prompts with a title and a genre, and pick them from drop-down lists.
- Choose a source image and a prompt, transform, and view the source and the result side by side.
- Mark results as favorites and rate them. You can trace later which image and which prompt produced each result.
- Transformation uses the OpenAI, Grok (xAI) and Gemini APIs. There is no monthly subscription, but **every transformation costs money**.
- See how much you have spent this month (an estimate) and set a monthly budget.

> **The user interface is in Japanese only.** This document gives each on-screen label in Japanese, followed by its meaning in English, so that you can find it on the screen.

---

## Disclaimer

This software is provided "as is". The author accepts no liability for any damage arising from the use of, or the inability to use, this software. Use it at your own risk, with the following points in mind.

- **You pay all API charges.** This software calls the paid APIs of OpenAI, xAI (Grok) and Google (Gemini) with the API keys that you register. The author accepts no liability whatsoever for charges incurred by transformations or style reading. This includes unintended charges caused by operating mistakes, configuration mistakes, defects in this software, or changes made by the providers.
- **You may be charged even when a request fails.** API charges can still apply when the output is blocked by a safety filter, when the response does not arrive in time, when the result cannot be saved, and in similar cases.
- **Amounts shown on screen are estimates.** They are figures recorded by this software and are not guaranteed to match what you are actually billed. The gap grows when a provider changes its prices. Check the actual charges in each provider's console. The monthly budget only tells you where you stand; it does not stop transformations or charges.
- **Images and prompts are sent to the providers' servers.** How they are handled is governed by each provider's terms of service and privacy policy. Do not use images that infringe someone else's rights or that show information you must not send.
- **No guarantee is given for generated images or text.** The author does not guarantee their accuracy or quality, nor that they are free from infringement of copyrights, portrait rights, trademarks or other rights. You are responsible for how you use the output and for complying with each provider's terms of service and content policy.
- **You are responsible for managing your API keys.** Keys are stored unencrypted in a file on this PC. Anyone who can use this PC can read them. The author accepts no liability for damage caused by leaked or misused keys.
- **No liability for lost data.** Prompts, images and history may be lost through defects, operating mistakes or hardware failure. Back up anything important. Deleted images cannot be restored.
- **No guarantee of operation.** The software may stop working without notice when a provider changes or ends its API.

**Before you use an API key, always do these two things.**

- **Give the key a short expiry. Never use long-lived or non-expiring keys.** If you cannot choose an expiry, disable the key in the provider's console when you finish, and create a new one the next time you need it.
- **Always set a spending limit in each provider's console.** The "monthly budget" in this app only tells you where you stand; it has no power to stop billing.

The legally binding text is the English text in `LICENSE` (MIT License). The explanation above describes its intent and the points specific to this software. The same content can be read in the app under the 「ヘルプ」 (Help) tab, in Japanese.

---

## 1. Requirements

| Item | Details |
|------|---------|
| OS | Windows 10 / 11 |
| Python | 3.10 or later (check with `python --version`). Not needed if you only use the app version |
| API key | One or more of OpenAI, xAI and Google. Issue the key in the provider's console and register a payment method there |
| Browser | Chrome, Edge or similar (for the browser version) |

## 2. First-time setup

Skip this section if you only use the app version (`PromptShop.exe`). It is needed for the browser version and for rebuilding the exe.

Open Command Prompt (or PowerShell) in the PromptShop folder and run this once:

```
pip install -r requirements.txt
```

## 3. Starting and stopping

PromptShop offers the same screen in two forms. **For everyday use, choose the app version in 3.1.**

### 3.1 App version (PromptShop.exe)

| Action | How |
|--------|-----|
| Get it | Download `PromptShop.exe` from GitHub Releases (https://github.com/markn333/PromptShop/releases). To build it yourself, use `build_exe.bat` (see "For developers") |
| Start | Double-click `PromptShop.exe`. A dedicated window opens in a few seconds (no console window, no browser) |
| Stop | Close the window |

- It requires Windows 10 / 11 and the Microsoft Edge WebView2 Runtime (included in Windows 11).
- The exe is a single file and runs without Python installed. You may move it anywhere or create a shortcut to it.
- On first launch Windows may show "Windows protected your PC", because the exe is not signed. Choose "More info" → "Run anyway".
- Only one instance can run at a time. A second launch shows a message and exits.
- If you try to close the window while a transformation is running, the app cancels the close once and shows a notice. Closing again within 10 seconds exits (in that case the call may have been charged, but it is not recorded in the history).
- Click an image to enlarge it inside the window. Click again for actual size, and use 「保存」 (Save) to save it to your PC.
- **The app version and the browser version in 3.2 keep their data in different places** (section 7).

### 3.2 Browser version (run.bat)

This form runs in a browser tab on a PC that has Python. It needs the setup in section 2.

| Action | How |
|--------|-----|
| Start | Double-click `run.bat`. A console window opens, and after a moment the screen appears in your browser |
| Stop | Press Ctrl+C in the console window, or close it |
| Reopen the screen | Open `http://127.0.0.1:8765/` in your browser |

- Closing the console window stops PromptShop. Keep it open while you work.
- The `data` folder is created automatically on first start.

## 4. Registering API keys

**Before you use an API key, always do these two things.**

- **Give the key a short expiry. Never use long-lived or non-expiring keys.** Where you can choose an expiry, choose one that covers only the period you need. Where you cannot, disable the key in the provider's console when you finish, and create a new one the next time. Do not leave unused keys active.
- **Always set a spending limit in each provider's console.** Set a monthly usage limit (budget cap), and turn off automatic top-up if you use prepaid credit. Without a limit, billing does not stop if a key leaks or you make a mistake. The "monthly budget" in this app only tells you where you stand; it has no power to stop billing.

1. Open the 「設定」 (Settings) tab at the top of the screen.
2. Paste the API key into the field for the provider you want and press 「保存」 (Save).
3. When 「登録済み（末尾 xxxx）」 (Registered, ending in xxxx) appears, you are done. No restart is needed.

- Keys are stored in the `.env` file on this PC. The screen shows only the last four characters.
- The key is not checked when you save it. If it is wrong, the first transformation shows 「API キーが正しくありません」 (The API key is not valid); you are not charged for that.
- Leave unused providers empty. A provider without a key cannot be selected on the transform screen.
- **Never show your API keys to anyone.** Do not paste them into chats or emails.

## 5. How to use

### 5.1 Registering prompts (「プロンプト」 Prompts tab)

1. Press 「新規」 (New), enter a title, genre and body, and press 「保存」 (Save).
2. Add, rename, reorder and delete genres under 「ジャンルの管理」 (Manage genres) on the same screen. It is collapsed by default; press its heading to open it. Deleting a genre keeps its prompts as 「未分類」 (Uncategorized).
3. Filter the list by genre and by keyword (title and body).
4. To edit a registered prompt, press its row in the list (the row shows 「編集」 (Edit) at the right end). The content appears on the right; change it and press 「保存」. 「削除」 (Delete) is there too.
5. When a prompt is open, 「これを使った変換結果」 (Results made with this prompt) are listed below it.

#### Creating a prompt from an image (style reading)

Show a reference image to an AI model and get a draft prompt that describes its style in words.

1. On the 「プロンプト」 tab press 「新規」, then open 「画像から下書きを作る」 (Create a draft from an image) at the top of the form (it is hidden while you are editing an existing prompt). Press 「画像ファイルを選ぶ」 (Choose an image file) to pick the reference image. You can also pick from images already imported or transformed.
2. Choose the provider used for reading and the language of the body (Japanese / English).
3. Press 「作風を読み取る」 (Read the style). A draft title and body are ready in a few seconds to about a minute.
4. If the form is empty, the draft is placed in it. If you have unsaved text there, it is not overwritten; press 「この下書きで入力欄を置き換える」 (Replace the form with this draft).
5. Check the content, adjust it if needed, and press 「保存」. **Nothing is registered as a prompt until you press Save.**

- Only the style is read (line work, coloring, palette handling, texture, lighting and so on). People and objects in the image are left out, because including them would change the content of the source image when you transform.
- **Each reading costs money** (see section 6 for a guide). You may be charged even when it fails.
- The text the AI writes varies slightly each time. If you do not like it, read again or try another provider.
- An image file chosen here also appears in the source-image list on the transform screen.

### 5.2 Transforming (「変換」 Transform tab)

1. Drop the source image onto the frame, or click the frame to choose a file (PNG / JPEG / WebP, up to 20 MB). Previously imported images and results can be chosen from the thumbnails below.
2. Choose a genre, then a title, from the drop-down lists; the body is filled in. You can edit the body on the spot (the saved prompt does not change). You can also transform by writing the body directly without choosing a prompt.
3. Choose a provider and press 「変換」 (Transform). It can take one to two minutes.
4. When it finishes, the source and the result appear side by side. Click an image to enlarge it.
5. Below the result you can add a favorite (♥) or a rating (★), or continue with 「これを元画像にして再変換」 (Transform again using this as the source).
6. When you choose a prompt and a provider, the 「作例」 (examples) registered for that combination appear as thumbnails (see 5.3 for how to register them). They help you judge the likely outcome.

- The original file is never modified. A copy of the imported image is saved in the `data` folder and used.
- The output aspect ratio is chosen automatically as the one closest to the source image (the size will not be exactly the same as the source).
- Unchecking 「縦横比維持」 (Keep aspect ratio) leaves the output shape to the provider. Use it when your prompt states a shape, such as "1:1 square". If the prompt states none, you get the provider's default shape (often square). The box is checked again when you restart the app.
- If a transformation fails, the reason is shown where the result would be. **It is never retried automatically.**

### 5.3 Managing results (「ギャラリー」 Gallery tab)

- Results are listed newest first. Filter by favorites only, rating, provider and prompt.
- Under each thumbnail are the title of the prompt that produced it and the provider. The title is the one in use at the time of the transformation.
- Press 「作例に登録」 (Register as example) to make a result the sample for the prompt and provider it used. It then appears on the transform screen when the same prompt and provider are chosen. Press again to remove it. Results made by typing the body directly, without choosing a prompt, cannot be examples.
- Press a thumbnail to open the details: the side-by-side comparison, the prompt used (the body as executed), and the chain of transformations from the first source image.
- 「削除」 (Delete) takes two presses. The image file is removed, but the history and cost records remain. **Deleted images cannot be restored.**
- Imported source images (including reference images) do not appear in the gallery. To delete one, select it under 「画像から選ぶ」 (Choose from images) on the 「変換」 tab and press 「この画像を削除」 (Delete this image), shown under the image, twice.

### 5.4 Checking costs (「料金」 Costs tab)

- See this month's total, the breakdown by provider, monthly totals and the list of failed transformations. Totals and counts include style reading (its own cost and count are also shown under the total). This month's total is always shown at the top right of the screen.
- You can set a monthly budget (USD). When this month's total reaches it, a confirmation appears before each transformation. Press 「それでも変換する」 (Transform anyway) to proceed. The budget is a guide; it does not block transformations.
- A month starts at 0:00 on the 1st, by this PC's clock.
- Pressing 「一覧をクリア」 (Clear the list) twice under 「失敗した変換」 (Failed transformations) empties that list. Cost records and counts are not removed.

### 5.5 Changing where data is kept (「設定」 Settings tab)

1. Under 「データの置き場」 (Data location) on the 「設定」 tab, enter the new folder (for example `D:\PromptShopData`) and press 「変更」 (Change).
2. If the folder is empty (or does not exist yet), the current data is copied there. The data in the old location is not deleted.
3. Close the app and start it again; it then uses the new location.

- If you specify a folder that already contains PromptShop data, nothing is copied and that data is used.
- The API key file is not moved.
- Avoid cloud-synchronized folders and network folders; the database can be damaged.
- If the location is on an external drive and you start the app without it connected, the app starts with the default location and shows a notice. Connect the drive and restart.
- After switching, delete the data in the old location yourself in Explorer if you no longer need it (the app does not delete it).
- Folder paths shown on screen are written like `%APPDATA%\PromptShop\data`, so that your Windows account name does not appear. Paste such a path into Explorer's address bar to open it.

### 5.6 Help (「ヘルプ」 Help tab)

- Shows the app version, the data location, usage instructions, the disclaimer and the licenses.
- **Read the disclaimer before you start.** You pay all API charges, and the author accepts no liability.

## 6. About costs

**Amounts on screen are estimates that this tool records for each call. Check the actual charges in each provider's console.**

| Provider | Model | Guide per transformation | How it is calculated |
|----------|-------|--------------------------|----------------------|
| OpenAI | `gpt-image-2.6-sunburst` | $0.05–0.07 | Usage in the response × unit price |
| Grok (xAI) | `grok-imagine-image-2.0` | $0.06 | Fixed (output $0.04 + input image $0.02; the input price is not published, so this is a provisional value) |
| Gemini | `gemini-nano-banana-2.1` | about $0.04 | Usage in the response × unit price |

Creating a prompt from an image (style reading) uses text models, separate from image transformation. The API keys are shared with image transformation.

| Provider | Model | Guide per reading | How it is calculated |
|----------|-------|-------------------|----------------------|
| OpenAI | `gpt-6.1-terra` | under $0.01 (about $0.003–0.006 in actual use) | Usage in the response × unit price |
| Grok (xAI) | `grok-4.7` | around $0.01 (expected) | Cost reported in the response (otherwise usage × unit price) |
| Gemini | `gemini-3.8-flash` | under $0.01 (expected) | Usage in the response × unit price |

- The guides for style reading are estimates from prices as of 2026-11-20. Only OpenAI has been checked against the real API; Grok and Gemini have not. The cost can rise depending on how much the model reasons. The estimated cost of each reading is shown on screen.
- Google states that the price of `gemini-3.8-flash` doubles from January 1, 2027. Update the prices in `app/config.py` at that time.
- The guides for transformation come from prices as of 2026-11-19 and from actual transformations. If prices change, update them in `app/config.py`.
- **You may be charged even when a request fails.** For example, Gemini charges even when the output is blocked by a safety filter. A response that does not arrive in time may also have been charged. Such cases are recorded as failures and included in the costs.
- Usage of the same API keys outside this tool is not included in the amounts on screen.
- To change the models, add lines like these to `.env` (they take effect after a restart):

  ```
  OPENAI_IMAGE_MODEL=model-name
  XAI_IMAGE_MODEL=model-name
  GEMINI_IMAGE_MODEL=model-name
  OPENAI_TEXT_MODEL=model-name
  XAI_TEXT_MODEL=model-name
  GEMINI_TEXT_MODEL=model-name
  ```

  `..._IMAGE_MODEL` is used for image transformation and `..._TEXT_MODEL` for style reading.

## 7. Where data is stored, and backups

The folder that holds the data depends on the form you use. **The two forms do not share data.**

| Form | Folder |
|------|--------|
| App version (`PromptShop.exe`) | `%APPDATA%\PromptShop` (paste it into Explorer's address bar to open it) |
| Browser version (`run.bat`) | The PromptShop folder (where `run.bat` is) |

The contents of that folder are the same for both forms.

| Location | Contents |
|----------|----------|
| `data/promptshop.db` | Prompts, genres, transformation history, cost records, budget |
| `data/sources/` | Imported source images |
| `data/results/` | Transformation results |
| `data/thumbs/` | Thumbnails for lists |
| `.env` | API keys |
| `promptshop.log` | Log of the app version (start, stop and errors; API keys are never written) |
| `webview/` | Working folder used by the app window (recreated if deleted) |

- To back up, exit PromptShop and copy the whole `data` folder. To restore, replace the folder while PromptShop is not running.
- `.env` and `data` are excluded from Git.
- To use a result elsewhere, click the image to enlarge it and press 「保存」 (Save).
- To move the app version to another PC, copy both the exe and the `%APPDATA%\PromptShop` folder.
- The data folder can be moved from the 「設定」 tab (5.5). The API key file stays where it is.

## 8. Troubleshooting

| Symptom | What to do |
|---------|------------|
| The app version does not start, or exits immediately | Check the end of `%APPDATA%\PromptShop\promptshop.log`. If it fails before the window appears, a message with the reason is shown |
| The app window stays blank | The Microsoft Edge WebView2 Runtime may be missing (it is included in Windows 11). Install it from Microsoft's download page |
| Nothing appears after running `run.bat` | Read the message in the console window. If it says `No module named ...`, do the setup in section 2 |
| The console window closes at once, or an error says the port is in use | Check whether PromptShop is already running. If another program uses port 8765, run `run.bat --port 8770` (or another number) in Command Prompt and open the URL shown |
| 「サーバーに接続できません」 (Cannot connect to the server) | Check that the console window is still open, and start again with `run.bat` |
| The Transform button cannot be pressed | The reason is shown beside the button (no API key / no source image / no body) |
| 「API キーが正しくありません」 (The API key is not valid) | Register the key again on the Settings tab |
| 「利用上限に達したか、残高が不足しています」 (Limit reached or insufficient balance) | Check your balance and usage limit in the provider's console |
| 「コンテンツポリシーにより拒否されました」 (Rejected by the content policy) | The image or the prompt was refused under the provider's rules. Change the content |
| 「別の変換を実行中です」 (Another transformation is running) | Only one transformation runs at a time. Wait for the previous one to finish |
| The screen looks outdated after an update | Reload in the browser (Ctrl+F5) |

To keep the browser from opening automatically, start with `run.bat --no-browser`.

## 9. Safety rules built in

- PromptShop can be opened only from this PC (it listens on `127.0.0.1` only). It is not visible from other PCs or from the internet.
- Pages on other websites cannot operate PromptShop behind your back (for example, to replace API keys or trigger unintended transformations).
- One press of the Transform button makes exactly one API call. A failure is never retried automatically. The button is disabled while a transformation runs, and two cannot run at once.
- API keys are never shown on screen, in logs or in the history.

## 10. What it cannot do

- Transform several images or several prompts in one batch
- Generate an image from text alone, without a source image
- Retrieve the actual amount billed by each provider
- Be shared with other people or published on the internet

---

## For developers

| Item | Details |
|------|---------|
| Stack | Python (FastAPI, SQLite) + a browser UI (HTML / CSS / JavaScript, no build step) |
| Specification | `SPEC.md` (Japanese) |
| Automated tests | `python -m pytest` (uses fake providers and temporary folders; never calls the real APIs and never touches `data` or `.env`) |
| Settings | `app/config.py` (port, limits, model IDs, prices) |
| Run the app version from source | `pip install -r requirements-desktop.txt`, then `python -m app.desktop` (data lives in the project folder, the same as the browser version) |
| Rebuild the exe | `build_exe.bat` (creates `dist\PromptShop.exe`; takes one to two minutes). **Run it in a clean virtual environment (venv) that contains only the required packages**; otherwise unrelated packages installed on your PC are bundled into the exe and the license list in the Help tab no longer matches. Code changes are not reflected in the exe until you rebuild |
| Use a different data folder | Set the environment variable `PROMPTSHOP_HOME` to a folder (useful for running against test data, separate from your real data) |

## License

PromptShop itself is released under the MIT License (see `LICENSE`). Copyright (c) 2026 REDSUN.

The software bundled in the app version (PromptShop.exe) and its licenses are listed in the app's 「ヘルプ」 (Help) tab and in `app/static/third_party_licenses.txt`. When you add or replace a dependency, update the list in `app/about.py` and then run `python tools/collect_licenses.py` (`build_exe.bat` also runs it before building the exe).
