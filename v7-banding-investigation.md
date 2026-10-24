# v7の周期的な濃淡 — 2026-10-24

利用者が紙そのものにも縞が見えると確認した。スキャンだけで発生するモアレでは説明できない。既存スキャンの300セル/インチの5パネルを切り出した `v7-300-band-crops.png` でも、複数のパネルに上下方向へ繰り返す濃淡の帯を確認できる。ただし用紙送り・印刷パス・ドライバーでの画像変換のどれが主因かはまだ未確定。

## 先に終えた位置合わせ診断

`diagnose_registration_v7.py` を元PNGと既存の実スキャンに実行。元PNGは対象8条件すべてで誤りゼロ・完全復元を確認。

実スキャンでは、既知の校正パターンだけで位置補正と判定を学習する方式、および元データのラベルを位置合わせ・学習に使う診断専用方式を明確に分離した。後者を実復号の成功とは扱わない。

| セル/インチ | 色数 | 校正位置補正を実データへ適用した候補の正答率 | 診断専用：局所位置合わせ＋隣接補正での検証セル正答率 |
|---|---:|---:|---:|
|200|8|95.57% / 98.44%|99.23%|
|200|16|69.34% / 89.55%|95.04%|
|250|8|72.07% / 83.34%|87.78%|
|250|16|53.69% / 66.99%|70.78%|
|300|8|80.56% / 76.24%|80.81%|
|300|16|51.38% / 52.64%|59.80%|
|400|8|19.78% / 16.99%|51.65%|
|400|16|30.96% / 25.68%|31.29%|

左列は校正位置の直接転用／そこから狭い範囲で画像コントラストを最適化する固定2方式。高密度で完全復元できた候補はない。右列はラベルを使って位置を合わせ、内部セルの約80%で色判定を学習、残り20%（1,694セル）で評価した診断結果。幾何補正で大幅に改善する条件はあるが、試した補正では誤りが多く残る。この数字を機器の限界や最適な到達精度とは解釈しない。

## 今回印刷した比較条件

既存の `best-quality-color-effective.xml` は、普通紙・カラー・最高画質・最高画質モードONである一方、`brpsk:PageBidirPrint=brpsk:On` だった。

同設定から双方向印刷だけOFFにしたジョブ専用DEVMODEを作成。ドライバーで往復変換した有効設定を検証済み:

- `psk:PageMediaType=psk:Plain`
- `psk:PageOutputQuality=psk:Photographic`
- `psk:PageOutputColor=psk:Color`
- `brpsk:PageAdvancedQualitySettings=brpsk:BestQuality`
- `brpsk:PageBidirPrint=brpsk:Off`

生成物は `best-quality-color-unidirectional.devmode` と `best-quality-color-unidirectional-effective.xml`。`prepare-unidirectional.ps1` で再生成できる。プリンターの既定値は変更していない。

同じ `calibrated-v7-print-1200dpi.png` をA4原寸・片面・1部で印刷送信。ジョブ名 `Paper N64 v7 - UNIDIRECTIONAL BANDING CONTROL - BEST`。内容が同一なので、今回排紙された用紙を前回の用紙と区別して保管する。効果は目視と次のスキャンで評価する。

## 公式情報と次の手段

Brotherは「濃い筋が周期的に入る」場合に用紙送りの確認・調整を案内し、この機種には用紙送り量補正と片方向印刷の設定がある。

- 印刷品質の問題: https://support.brother.co.jp/j/s/support/html/cv_mfcj742dn_jpn_a/doc/html/GUID-F791545A-17F8-4F8B-87D7-615C9CD70B1C_1.html?c=jp&lang=ja&prod=dcpj929n
- 用紙送り量の補正: https://support.brother.co.jp/j/s/support/html/cv_mfcj742dn_jpn_a/doc/html/GUID-C3BD0361-3C1B-4D70-A946-F7AA23F94429_1.html
- 機種共通設定一覧（DCP-J1270N含む）: https://support.brother.co.jp/j/s/support/html/cv_mfcj742dn_jpn_a/doc/html/GUID-069DB7B2-8F4E-4D62-BE9B-10EBF5AC97B1_1.html

片方向印刷で改善しなければ、本体の印刷品質チェック→用紙送り量の補正→必要に応じ罫線ずれ補正を試す。操作パネルのチェックシートに基づく調整はまだ実施していない。

また有効PrintTicketのPageResolutionは600×600で、これは物理的なインク滴の解像度を示すとは限らない。入力1200dpi画像から印刷用ラスターへの変換も確認対象。用紙送りだけを原因と断定せず、必要なら画素格子へ合わせた描画や画像拡縮を避ける描画方法を比較する。
