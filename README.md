# 🚄 THSR Seat Alert：高鐵空位監控＋開賣提醒

連假高鐵票總是秒殺？這個工具會在 **GitHub Actions 上每 10 分鐘自動檢查**一次，然後用 Email 通知你：

- ⏰ **開賣前提醒**：照你設定的「開賣前幾天、幾小時、幾分鐘」寄信，讓你準時守在電腦前
- 🔔 **開賣當下通知**
- 🎫 **有人退票時馬上通知**：符合你設定的日期、時段、車廂，有車次從「已售完」變成「有座位」就寄信
- 📅 **自己選要盯哪些節日**：在 `config.yaml` 開關節日、設定去回程路線和時段

> **這個工具只負責通知，不會幫你自動訂票。**
> 資料來自交通部 [TDX 運輸資料流通服務](https://tdx.transportdata.tw/) 的官方開放 API，不爬高鐵訂票網站，也不會破解驗證碼。
> 收到通知後，請自己用 [高鐵官網](https://irs.thsrc.com.tw/IMINT/) 或「T Express」App 訂票。
> 依《鐵路法》第 65 條，用程式自動購票可能觸法。

---

## ⚙️ 第一次設定（約 10 分鐘）

### 1. 申請 TDX API 金鑰（免費）
1. 到 <https://tdx.transportdata.tw/register> 註冊會員，並完成 Email 驗證
2. 登入後進入「會員中心 → 資料服務 → API 金鑰」，複製 **Client Id** 和 **Client Secret**

### 2. 申請 Gmail 應用程式密碼（用來寄通知信）
1. 寄件的 Google 帳號要先開啟 [兩步驟驗證](https://myaccount.google.com/signinoptions/two-step-verification)
2. 到 <https://myaccount.google.com/apppasswords> 新增一組應用程式密碼，會拿到 16 碼的英文字母

### 3. 把金鑰設定到 GitHub Secrets
在 repo 的 **Settings → Secrets and variables → Actions → New repository secret** 新增：

| Name | 值 |
|---|---|
| `TDX_CLIENT_ID` | TDX Client Id |
| `TDX_CLIENT_SECRET` | TDX Client Secret |
| `SMTP_USER` | 寄件 Gmail 地址 |
| `SMTP_PASSWORD` | 16 碼應用程式密碼 |
| `NOTIFY_EMAIL` | 收通知的 Email |

也可以用指令設定：
```bash
gh secret set TDX_CLIENT_ID
gh secret set TDX_CLIENT_SECRET
gh secret set SMTP_USER
gh secret set SMTP_PASSWORD
```

### 4. 測試
到 **Actions → THSR Seat Alert → Run workflow** 手動執行一次，確認執行結果是綠色勾勾。

---

## 📝 設定要盯哪些節日：`config.yaml`

```yaml
trips:
  - name: 2027 春節
    holiday: 2027春節            # 對應 holidays.yaml
    enabled: true                # false = 先不監控
    remind_before_sale: [7d, 1d, 2h, 10m]   # 開賣前多久提醒
    legs:
      - label: 去程
        date: start-1            # 連假前一天出發
        from: 台北
        to: 左營
        depart_after: "17:00"    # 只看 17:00~22:00 出發的車
        depart_before: "22:00"
        car: standard            # standard / business / any
        # trains: ["0661"]       # （選填）只盯特定車次
```

- `date` 可以寫：`start`、`start-1`、`end`、`end+1`，也可以直接寫日期 `2027-02-03`
- 節日日期寫在 `holidays.yaml`，請對照 [人事行政總處公告](https://www.dgpa.gov.tw/) 確認
- 春節等疏運期間如果高鐵另外公告開賣時間，在 `holidays.yaml` 填上 `sale_open: "2027-01-05 00:00"`

改完 push 上去就會生效。想在本機先看排程：
```bash
pip install -r requirements.txt
python -m thsr_alert plan
```

---

## 🖥️ 在自己電腦持續監控（選用）
GitHub 排程有時會延遲幾分鐘。如果想更即時，可以在自己的電腦上跑：
```bash
export TDX_CLIENT_ID=... TDX_CLIENT_SECRET=... SMTP_USER=... SMTP_PASSWORD=... NOTIFY_EMAIL=...
python -m thsr_alert run --loop 300      # 每 5 分鐘檢查一次
python -m thsr_alert run --dry-run       # 只印出、不寄信
python -m thsr_alert test-email          # 寄測試信
```

---

## ⚠️ 限制
- **TDX 官方剩餘座位資料的更新頻率**：乘車**當天**每 10 分鐘更新；**預售期間（明天到 27 天後）**每天只在 **10:00、16:00、22:00** 更新三次。所以預售期間的退票通知，最快會在這三個時間點後收到。
- GitHub 的排程可能延遲 5～15 分鐘，所以「開賣前 10 分鐘」這種很短的提醒，可能會晚一點才到。
- 公開 repo 如果 60 天沒有任何 commit，GitHub 會自動停用排程。到 Actions 頁面按 Enable 就能恢復。
- 同一個車次只會在「售完 → 有位」時通知一次，不會一直重複寄信。

## 🧪 測試
```bash
python -m unittest discover -s tests -t . -v
```
