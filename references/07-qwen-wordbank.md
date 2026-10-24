# 07 · Qwen-Image 2.1 取词库（人物 / 场景 / 道具）

**数据源**：`references/qwen-wordbank.json`（41 个槽位、367 条英文词条）。
**来源**：从 `ComfyUI-Luori-Sunset` 的 `data/lr/*.json`（93 字段、数百条中文选项，原为 Z-Image 设计）抽出，
按本技能"只做人物 / 场景 / 道具三类资产"的范围裁剪、改写成英文短词条，去掉用不上的（动作、表情戏、多人物互动、NSFW、写真主题 120 条等）。

> 这份词库**只管取词**。行文规则（观察者口吻、方位清单、八步框架、五条硬禁令）仍是
> `03-qwen-image-prompt.md`；该建什么资产、要交代哪些信息，是 `02-asset-prompt-spec.md`。
> 视频镜头的运镜另有一套（`06-camera-moves.md`），**不要混用**。

---

## 一、三条硬规矩

1. **一个资产 = 一条提示词**。不给备选、不写 A/B 版、不在 `assets[].prompt` 里放两段。
   要改就改这一条，改完再给人看。多条候选只会让人挑花眼，也让提示词互相污染。
2. **一个槽取一个词（或一个词族）**。`oval face` 和 `round face` 同时出现，模型会给你一张糊脸。
   同义词堆叠（`beautiful, stunning, gorgeous`）是负收益。
3. **只写看得见的**。人物不写动作/情绪戏/场景/光位；场景不写人；道具不写手。

---

## 二、五步取词（写任何一条资产提示词都走这五步）

| 步 | 做什么 | 落在哪 |
|---|---|---|
| 1 | 定资产类型，打开对应槽位顺序表（下面第三节） | 选槽 |
| 2 | 按顺序逐槽取 **1** 个词条，填满 8–16 个槽（别全填，见配额） | 取词 |
| 3 | 把词条**扩写成句子**（加方位、加材质因果、加数量），不直接罗列逗号串 | 成句 |
| 4 | 补真实感：从 `global.realism` 挑 2–3 条；补光一句、镜头一句 | 落地 |
| 5 | 通读：每个槽只出现一次？没有互斥（长发+寸头、素颜+浓妆）？没有空词？ | 自检 |

> 词条是**半成品**：`high cheekbones and a defined jawline` 要变成
> `High cheekbones and a defined jawline give the face a hard, angular read in the upper-left of the sheet.`

---

## 三、槽位顺序（顺序即句子顺序，别乱）

### 3.1 人物（18 槽，挑 12–16）

`age → look → face → eyes → brows_nose → lips → skin → hair_len → hair_tex → hair_color → build → top → bottom → fabric_detail → worn → accessory → hands → expression`

- **必须有的**：age、face、eyes、hair（长/质/色三槽）、skin、top+bottom 或连衣裙、build。
- **可省的**：accessory（人物设定里没有就写 `no jewellery`）、hands（不拍手就省）、worn（衣服本身不旧就省）。
- 顺序的道理：**先骨相后皮肉，先本体后衣着**——模型先立结构，再贴细节，不容易糊。

### 3.2 场景（10 槽，挑 8–10）

`location → time → weather → structure → surfaces → furnishing → worn → light → color → air`

- **必须有的**：location、structure、surfaces、furnishing、light；其余按戏需要。
- `light` **单独一句**，来源 + 方向 + 质地 + 落点，一句写完（这条和 03 的第 7 步是同一件事）。
- `worn` 是场景的灵魂：没有它，再贵的场景也像样板间。

### 3.3 道具（8 槽，全用）

`object → material → craft → size → finish → worn → marks → light`

- `size` 一定要给参照物（`no longer than a palm`），否则模型给你一个谜之尺度。
- `marks` 只写磨损的刻字/编号，**不写能读的品牌名**（等于让模型去画文字，必糊）。

---

## 四、配额（超了就是堆砌）

| 资产 | 槽数 | 条数上限 | 英文词数 |
|---|---|---|---|
| 人物 | 12–16 / 18 | 配饰 ≤3 件、真实感瑕疵 2–3 条 | 350–500 |
| 场景 | 8–10 / 10 | 陈设 3–5 件、痕迹 2–3 条、光 1 句 | 350–500 |
| 道具 | 8 / 8 | 痕迹 1–2 条、特征细节 1–2 条 | 300–450 |

**判断标准**：删掉某个词条，这张图会不一样吗？不会 → 删掉。

---

## 五、真实感补丁（专治 AI 塑料感）

从 `global.realism` 里挑 2–3 条，**不要全列**。优先级从高到低：

1. 皮肤层：`visible pores on the nose and cheeks` / `fine baby hairs along the hairline` / `a few faint freckles across the bridge of the nose`
2. 结构层：`slight natural asymmetry between the left and right side` / `thin creases at the outer corners of the eyes`
3. 材质层（服装/道具/场景通用）：`fabric with soft pilling and a faded edge` / `the edges rounded by handling` / `dust settled in the seams and corners`
4. 身体层：`chapped cuticles` / `fingernails with natural wear at the tips` / `faint shadow of stubble along the jaw`

> 用户口径（见 03 的 4.1.1）：**真人质感 + 明确美颜**。毛孔和绒毛要留，但底子要好看；
> 痣、疤、斑点这类"来由不明的特征"一律不写，除非剧本里写了。

---

## 六、正例（每类一条，都是压缩示例，实际按词数配额展开）

**人物**

> A photographic character reference sheet of a woman in her late thirties, East Asian features.
> A balanced oval face with high cheekbones and a defined jawline; almond-shaped dark brown eyes with a visible catchlight; straight natural brows, slightly sparse at the tails; a full upper lip with a defined cupid's bow, bare in a muted rose tone.
> A warm light-olive skin tone, matte with a faint sheen on the T-zone, visible pores on the nose and cheeks and a few faint freckles across the bridge of the nose.
> Shoulder-length hair, straight and fine, a side-parted sweep with a few strands out of place, natural black with a cool sheen.
> Slim with narrow shoulders. A stiff-collared work shirt in a coarse linen weave, slightly oversized and boxy, the collar softened and slightly greyed and a frayed cuff on one sleeve; straight-leg dark denim jeans, faded at the knees.
> A thin silver chain at the throat, a plain wedding band on the left hand. Long fingers, short practical nails, a callus across the palm.
> A calm neutral expression, a level steady gaze into the lens. Against a plain seamless light-grey studio background.
> Shot on an 85mm prime lens at eye level, shallow depth of field, the face fully in focus. No text, no watermark, no CGI look.

**场景**

> A photographic interior of a cramped old-style interrogation room, deep night, rain just stopped and everything wet.
> A single high window with frosted glass and a floor drain with a rusted grate; walls of painted brick with the paint blistering at the lower third, an oiled hardwood floor worn pale along the centre, a ceiling of bare joists.
> A metal table bolted to the floor in the middle of the frame, a chair with one broken slat pushed back from it, a wall clock stopped at ten past two high on the right wall, three cardboard boxes stacked in the far corner.
> Water stains spreading from the ceiling corner, dust in every seam and on the window ledge, cigarette burns along the table edge.
> Light from a single bare bulb overhead, hard, throwing deep shadows under the table and a hard-edged pool of light on the floor; dust visible in the beam.
> A muted palette of grey, dirty white and rust. Shot on a 35mm lens at chest height, deep focus from the front edge to the far wall. No people, no text, no watermark.

**道具**

> A photographic still life of a folding pocket knife with a worn wooden handle, cast iron blade housing with a pitted surface, hand-forged with hammer marks still visible along the spine.
> No longer than a palm. A dull patina over the whole surface, the edges rounded by handling, a deep scratch across the right face, an engraved initial worn almost smooth near the pivot.
> Hard direct light from the upper left with a single sharp highlight along the top edge, soft falloff into the background.
> On a matte dark-grey surface, the background falling off to black. Shot on a 100mm macro lens, flat field. No hands, no text, no watermark.

---

## 七、反例对照

| 写法 | 问题 | 改成 |
|---|---|---|
| `beautiful woman, gorgeous, stunning` | 空词，零信息 | `a balanced oval face with high cheekbones` |
| `long straight black hair, short hair` | 互斥槽同时出现 | 只留一个：`hair to the mid-back, straight and thick` |
| `wearing a nice dress` | 没材质没版型 | `a knee-length A-line dress in crinkled raw silk, loose drape` |
| `a room with furniture` | 没结构没痕迹 | `walls of painted brick with blistering paint, a metal table bolted to the floor, dust in every seam` |
| `a knife, 8K, masterpiece` | 空词 + 没材质 | `a folding pocket knife, cast iron with a pitted surface` |
| `she looks sad and scared` | 资产图不演戏 | `a calm neutral expression, a level steady gaze` |
| 同一资产写两段提示词给人选 | 违反"只出一条" | 合成一条，把有分歧的点写成注释让人改 |

---

## 八、写完自检（连同 03 第七节一起过）

- [ ] 只出了**一条**？没有备选段落？
- [ ] 每个槽只出现一次？没有互斥（长发/短发、素颜/浓妆、干净/脏污）？
- [ ] 词条扩写成句子了？不是逗号串？
- [ ] 有 2–3 条真实感补丁？没有 `8K / masterpiece / stunning`？
- [ ] 人物没写动作/场景/光位？场景没写人？道具没写手？
- [ ] 收尾有镜头一句 + 画质/禁止项一句？
- [ ] 词数在配额内（人物 / 场景 350–500，道具 300–450）？

---

## 九、附录：一条完整的人物提示词（约 480 词，照着这个密度写）

下面这条是把第三节的 18 个槽按顺序填满后的成稿。**注意三件事**：槽位顺序没乱、每个槽只出现一次、
所有词条都扩成了带方位的句子——这就是"更详细"该有的样子，不是把形容词堆得更多。

> A photographic character reference sheet of a woman in her late thirties, East Asian features,
> read as one continuous design against a plain seamless light-grey studio background.
> A balanced oval face with high cheekbones and a defined jawline; the forehead is low and broad and the chin
> is short, which pulls the face into a compact, watchful shape across the upper-left third of the sheet.
> Almond-shaped dark brown eyes with a visible catchlight sit under straight natural brows that are slightly
> sparse at the tails; a straight nose with a rounded tip runs down the centre line, and a full upper lip with a
> defined cupid's bow closes over a wide mouth whose corners turn up only faintly.
> A warm light-olive skin tone, matte across the cheeks with a faint sheen on the T-zone, visible pores on the
> nose and cheeks and a few faint freckles scattered across the bridge of the nose. Thin creases sit at the outer
> corners of each eye, and there is slight natural asymmetry between the two sides of the face — one brow
> sits a few millimetres higher than the other.
> Shoulder-length hair, straight and fine, parted on the left and swept across so that a few strands fall out of
> place along the right cheek; the colour is natural black with a cool sheen that picks up a narrow highlight
> along the crown.
> The build is slim with narrow shoulders and a short torso, the weight carried easily rather than posed.
> She wears a stiff-collared work shirt in a coarse linen weave, cut slightly oversized and boxy so the shoulder
> seam falls past the shoulder point; the collar has softened and greyed with washing, one cuff is frayed into
> loose threads, and the placket is wrinkled rather than pressed.
> Below, straight-leg dark denim jeans faded at the knees and a pair of scuffed leather work shoes.
> A thin silver chain sits at the throat and a plain wedding band turns on the left hand; there is no other
> jewellery.
> The hands are long-fingered with short practical nails, a callus across the right palm and chapped cuticles.
> The expression is calm and neutral, the mouth closed and relaxed, the gaze level and steady into the lens.
> A single soft light from the upper left wraps the face, falling off toward the right cheek and leaving a soft
> shadow under the jaw, a weak fill keeping the shadow side readable rather than black.
> The overall composition balances a large face study on the left against a full standing figure in the centre and
> a back view on the right, the three views sharing one light direction and one colour temperature throughout,
> with a muted palette of warm grey, off-white and faded indigo. Shot on an 85mm prime lens at eye level, shallow
> depth of field, the face fully in focus. No text, no watermark, no logo, no CGI look, no beauty filter.

自检这条：18 槽用到 16 槽（`accessory` 只写项链与戒指、`no other jewellery` 收口；`hair_len` 与 `hair_tex` 合成一句），
真实感补丁 3 条（毛孔雀斑 / 眼角细纹 / 左右轻微不对称），互斥词 0 处，词数约 480（上限 500，超了就是在堆砌）。
