# Agent Browser

> [browser-use](https://github.com/browser-use/browser-use) に基づく検知回避ブラウザ自動化フレームワーク。

**Note:** これは [英語版 README](README.md) の翻訳です。最新情報は原文を参照してください。

## 概要

Agent Browser は **browser-use** に産業級の検知回避機能、YAML パイプラインエンジン、サイト探索、アダプタ合成機能を追加します。検知システムでブロックされる **browser-use 上級ユーザー** のために設計されています。

## 主な機能

- **7層検知回避スタック** — C++ フィンガープリント偽装からサーキットブレーカーまで完全防御
- **YAML パイプラインエンジン v2.3** — 19種フィルター、エラー分類、自動復旧
- **サイト探索モジュール — 自動DOM解析とアダプタ生成
- **browser-use ネイティブ統合** — browser-use の検知回避拡張レイヤー

## クイックスタート

### インストール

```bash
# ベーシック（ステルス層6-7のみ、標準 Playwright で動作）
pip install agent-browser

# フル検知回避（全7層、CloakBrowser 要）
pip install agent-browser[cloak]

# サーバーモード含む（FastAPI + LLM 統合）
pip install agent-browser[full]
```

### 基本的な使い方

```python
import asyncio
from agent_browser import create_session, open_page, snapshot, click, fill

async def main():
    # ステルスラップされたブラウザセッションを作成
    session_id = await create_session()

    # ページへ移動（自動ステルス遅延適用）
    await open_page(session_id, "https://example.com")

    # スナップショット取得（ref付きのインタラクティブ要素を返す）
    data = await snapshot(session_id)
    print(f"Found {len(data['elements'])} elements")

    # 要素refを使用して操作
    await click(session_id, "@e0")  # 最初のインタラクティブ要素をクリック
    await fill(session_id, "@e1", "hello world")

asyncio.run(main())
```

## ライセンス

Apache 2.0。詳細は [LICENSE](LICENSE) を参照してください。
