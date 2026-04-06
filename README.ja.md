[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![PyPI version](https://img.shields.io/pypi/v/agent-browser.svg)](https://pypi.org/project/agent-browser/)
[![CI](https://github.com/galen/agent-browser/actions/workflows/ci.yml/badge.svg)](https://github.com/galen/agent-browser/actions/workflows/ci.yml)

# Agent Browser

> [browser-use](https://github.com/browser-use/browser-use) に基づく検知回避ブラウザ自動化フレームワーク。

Agent Browser は **browser-use** に産業級の検知回避機能、YAML パイプラインエンジン v2.3、サイト探索、アダプタ合成機能を追加します。検知システムでブロックされる **browser-use 上級ユーザー** のために設計されています。

## 主な機能

- **検知回避** -- C++ フィンガープリント偽装から AI 駆動のサーキットブレーカーまで 7 層防御
- **大規模自動化** -- YAML パイプラインエンジン v2.3（自動復旧、エラー分類、シングルステップデバッガ）
- **どこでも動作** -- CLI、REST API、Python ライブラリ；ローカルブラウザ、Chrome 拡張、リモートゲートウェイ
- **サイト探索** -- 自動 DOM 分析 + カスケード CSS セレクタ生成 + YAML アダプタ合成

## クイックスタート

```bash
pip install agent-browser
```

```python
import asyncio
from agent_browser import create_session, open_page, snapshot, click, fill

async def main():
    session_id = await create_session()
    await open_page(session_id, "https://example.com")

    data = await snapshot(session_id)
    print(f"{len(data['elements'])} 個のインタラクティブ要素を検出")

    await click(session_id, "@e0")       # 要素参照でクリック
    await fill(session_id, "@e1", "hello") # 入力フィールドに入力

asyncio.run(main())
```

## 機能詳細

### 検知回避（7 層）

| 層 | コンポーネント | 機能 |
|----|-------------|------|
| 1 | CloakBrowser | C++ レベル指紋偽装（33 パッチ） |
| 2 | patchright | ドライバーレベル CDP パッチ |
| 3 | rebrowser-patches | Runtime.Enable リーク修正 |
| 4 | 非標準ポート 19222 | 接続難読化 |
| 5 | 永続化 CDP セッション | 頻繁な attach/detach を防止 |
| 6 | StealthEnhancer | 人間風遅延、ベジェマウスカーブ、1 文字ずつ入力 |
| 7 | StealthMiddleware | 集中型ステルス層 + Per-session サーキットブレーカー |

### パイプラインエンジン v2.3

- YAML ドり自動化パイプライン
- 19 種のテンプレートフィルタ（算術式対応）
- 型付きエラー階層（6 カテゴリ）
- 自動エラー分類と復旧
- シングルステップデバッガ + ブレークポイント
- JSONL テレメトリ実行トレース

### マルチモード対応

| モ�式 | ブラウザ | インテリジェンス | ユ用シーン |
|------|----------|----------------|-----------|
| CLI + local | CloakBrowser / Playwright | LLM / Agent | ローカル開発 |
| CLI + extension | ユーザ Chrome（本物指紋） | LLM / Agent | 本番スクレイピング |
| API + local | FastAPI -> ローカル CDP | LLM / Agent | チームサーバー |
| API + remote | FastAPI -> Docker GW | LLM / Agent | 分散クラスター |

### サイト探索とアダプタ合成

- 自動 DOM 構造解析
- カスケード CSS セレクタ生成
- 探索結果から YAML アダプタをワンコマンドで生成

## インストール

```bash
# ベーシック（ステルス層 6-7 のみ、標準 Playwright で動作）
pip install agent-browser

# フル検知回避（全 7 層、CloakBrowser 要）
pip install agent-browser[cloak]

# サーバーモード含む（FastAPI + LLM 統合）
pip install agent-browser[full]
```

<details>
<summary>ソースからインストール</summary>

```bash
git clone https://github.com/galen/agent-browser.git
cd agent-browser
pip install -e ".[full]"
playwright install chromium
```

</details>

## 使い方

### 関数型 API

```python
import asyncio
from agent_browser import create_session, open_page, snapshot, click, fill, evaluate

async def main():
    session_id = await create_session()
    await open_page(session_id, "https://example.com")
    data = await snapshot(session_id)

    await click(session_id, "@e0")
    await fill(session_id, "@e1", "hello world")
    title = await evaluate(session_id, "document.title")

asyncio.run(main())
```

### OOP インターフェース

```python
import asyncio
from agent_browser import AgentBrowser

async def main():
    async with AgentBrowser() as ab:
        await ab.create_session()
        await ab.open_page("https://example.com")
        snap = await ab.snapshot()
        await ab.click("@e0")
        result = await ab.run_task("検索ボックスを見つけて 'python' と入力")
        print(result['status'])

asyncio.run(main())
```

### サーバーモード（FastAPI）

```bash
pip install agent-browser[full]
uvicorn agent_browser.api:app --port 8000
curl http://localhost:8000/health
```

**REST API エンドポイント：**

| メソッド | エンドポイント | 説明 |
|---------|---------------|------|
| GET | `/health` | サーバー健全性 + プール統計 |
| POST | `/sessions/create` | セッション作成 |
| GET | `/sessions/{id}` | セッション状態 |
| DELETE | `/sessions/{id}` | セッション削除 |
| POST | `/navigate` | URL へナビゲート |
| POST | `/snapshot` | DOM スナップショット |
| POST | `/click` | 要素参照でクリック |
| POST | `/fill` | 入力フィールド入力 |
| POST | `/evaluate` | JavaScript 実行 |
| POST | `/task` | LLM/Agent タスク送信 |

### パイプラインモード

```python
from agent_browser.pipeline import PipelineExecutor

executor = PipelineExecutor(stealth_enabled=True)
result = await executor.run("adapters/my-site.yaml")
```

### 探索モード

```python
from agent_browser.explore import Explorer, Synthesizer
from agent_browser import create_session, open_page

async def main():
    session_id = await create_session()
    await open_page(session_id, "https://target.com")

    explorer = Explorer(session_id)
    snapshot = await explorer.explore()

    # 探索結果からアダプタ YAML を自動生成
    adapter_yaml = Synthesizer.synthesize(snapshot)
    print(adapter_yaml)

asyncio.run(main())
```

### CLI

```bash
agent-browser --help
```

## 公開 API リファレンス

| 関数 | 説明 |
|------|------|
| `create_session()` | ブラウザセッション作成、UUID を返す |
| `open_page(sid, url)` | URL へナビゲート |
| `snapshot(sid)` | DOM スナップショット取得（`@eN` 要素参照付き） |
| `click(sid, ref)` | 要素参照でクリック (`"@e0"`) |
| `fill(sid, ref, text)` | 入力要素にテキスト入力 |
| `scroll(sid, direction, amount)` | ページスクロール |
| `select_option(sid, ref, value)` | ドロップダウン選択 |
| `hover(sid, ref)` | マウスを要素中央へ移動 |
| `press_key(sid, key)` | キーボードキー押下 |
| `wait_for_selector(sel, timeout)` | CSS セレクタ待機 |
| `go_back(sid)` | 戻る |
| `evaluate(sid, expr)` | JS 実行、結果返却 |
| `run_task(sid, task, intelligence)` | LLM/Agent 自律タスク |
| `delete_session(sid)` | セッションリソース解放 |
| `configure(**kwargs)` | 次回セッション用設定更新 |
| `reset()` | 全グローバル状態クリア |
| `setup()` | 完全初期セットアップ＆検証 |

## アーキテクチャ

```
agent_browser/
├── __init__.py      # 公開 API エクスポート + __version__
├── main.py          # ファサード API（create_session, snapshot, click, run_task 等）
├── client.py        # AgentBrowser OOP インターフェース（セッショントラッキング、コンテキストマネージャ）
├── config.py        # SkillConfig データクラス + モード検出
├── browser/         # バックエンド ABC + 実装（local, remote, extension）
├── stealth/         # 検知回避：middleware, enhancer, actions, patches
├── pipeline/        # YAML パイプラインエンジン v2.3
├── explore/         # サイト探索 + アダプタ合成
├── adapters/        # サイトアダプタ ローダ/ランナー/バリデータ
├── intelligence/    # Agent タスク実行（browser-use 統合）
├── session/         # マルチユーザーセッション管理
├── cli/             # コマンドラインインターフェース（Typer）
├── llm/             # LLM ファクトリ（OpenAI, Anthropic, GLM）
└── utils/           # 共通ユーティリティ
```

完全なアーキテクチャガイドは [CLAUDE.md](CLAUDE.md) を参照してください。

## 例

[`examples/`](examples/) ディレクトリ参照：

- [`examples/getting_started/`](examples/getting_started/) -- 基本検索、スナップショット探索、Agent タスク、サイト別例（Zhihu, Bilibili, バッチ検索）
- [`examples/advanced/`](examples/advanced/) -- 上級使い方パターン

## browser-use との比較

| 機能 | browser-use | Agent Browser |
|------|------------|-------------|
| AI Agent 自動化 | 対応 | 対応（browser-use ラッパー） |
| 検知回避 | なし | 7 層防御スタック |
| 人間挙動シミュレーション | なし | ベジェマウス、1 文字ずつ入力 |
| サーキットブレーカー | なし | Per-session 自動ダウングレード |
| YAML パイプラインエンジン | なし | 19 フィルターテンプレートエンジン |
| エラー分類 | なし | 6 カテゴリ型付きエラー |
| 自動復旧 | なし | エラーカテゴリ別フォールバック |
| サイト探索 | なし | DOM 分析 → アダプタ生成 |
| テレメトリ | なし | JSONL 実行トレース |
| デバッガ | なし | シングルステップ + ブレークポイント |

## 依存関係

### コア依存（常にインストール）

- `browser-use>=0.12.0` - AI ブラウザエージェントフレームワーク
- `playwright>=1.40.0` - ブラウザ自動化
- `pydantic>=2.0` - データバリデーション
- `PyYAML>=6.0` - YAML 設定/パイプライン解析
- `structlog>=24.0` - 構造化ログ
- `aiohttp>=3.9.0` - 非同期 HTTP クライアント

### オプション依存

- `[cloak]` - CloakBrowser C++ 指紋 + patchright（第 1-5 層）
- `[full]` - FastAPI サーバー + LLM 統合（langchain-openai, langchain-anthropic）

## ドキュメント

- [アーキテクチャガイド](CLAUDE.md) -- 完全システム設計、モードマトリクス、開発規約
- [貢献ガイド](CONTRIBUTING.md) -- 開発環境セットアップ、コードスタイル、PR プロセス
- [セキュリティポリシー](SECURITY.md) -- 脆弱性報告、セキュリティベストプラクティス
- [デプロイガイド](deploy/README.md) -- Docker、Kubernetes、Helm デプロイ
- [CHANGELOG](CHANGELOG.md) -- バージョン履歴

## 貢献

歓迎します！詳しくは [CONTRIBUTING.md](CONTRIBUTING.md) を参照：

- 開発環境セットアップ
- コードスタイル規約（ruff フォーマッタ/linter）
- PR プロセス
- テストスイート（868 テスト、unit/integration/scenario/stealth/browser/skill を網羅）

## ライセンス

Apache 2.0。詳細は [LICENSE](LICENSE) を参照。

## 謝辞

以下の優れたオープンソースプロジェクトに基づいて構築されています：

- [browser-use](https://github.com/browser-use/browser-use) -- AI ブラウザエージェントフレームワーク（MIT）
- [Playwright](https://github.com/microsoft/playwright) -- 信頼性の高いブラウザ自動化（Apache 2.0）
- [CloakBrowser](https://github.com/nickyc975/cloakbrowser) -- C++ 検知回避 Chromium（MIT）
