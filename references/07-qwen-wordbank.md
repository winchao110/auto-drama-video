# 07 · 生图取词库（人物 / 场景 / 道具）· Qwen 系 CLIP 通用

**数据源**：`references/qwen-wordbank.json`（42 个槽位、370 条英文词条）。
**来源**：从 `ComfyUI-Luori-Sunset` 的 `data/lr/*.json`（93 字段、数百条中文选项，原为 Z-Image 设计）抽出，
按本技能"只做人物 / 场景 / 道具三类资产"的范围裁剪、改写成英文短词条，去掉用不上的（动作、表情戏、多人物互动、NSFW、写真主题 120 条等）。

> 这份词库**只管取词**。行文规则（观察者口吻、方位清单、八步框架、五条硬禁令）仍是
> `03-qwen-image-prompt.md`；该建什么资产、要交代哪些信息，是 `02-asset-prompt-spec.md`。
> 视频镜头的运镜另有一套（`06-camera-moves.md`），**不要混用**。

---

## 一、四条硬规矩

1. **一个资产 = 一条提示词**。不给备选、不写 A/B 版、不在 `assets[].prompt` 里放两段。
   要改就改这一条，改完再给人看。
2. **一个槽取一个词（或一个词族）**。`oval face` 和 `round face` 同时出现，模型会给你一张糊脸；
   同义词堆叠（`beautiful, stunning, gorgeous`）是负收益。
3. **默认把人写好看、写体面**。这是短剧，不是社会纪实。皮肤给质感与健康光泽，头发给整洁发型，
   衣服给干净挺括——**不要用"毛孔清晰可见 / 无修图 / 干裂 / 凌乱 / 皱巴巴"去换"真实"**，
   那不是真实，是丑。
4. **瑕疵要剧本批准**。痣、疤、伤口、痘印、干裂嘴唇、油光、污渍、破衣烂衫 —— 只有当剧本/人设
   明确写到（被打过、逃难过、干过粗活），才从 `flaw` / `worn` 两个"剧情专用槽"里取 **1 条**，
   并在 `assets[].note` 里记一句"哪个剧情需要"。没写清楚的一律不取。

> 一句话：**质感靠光和材质，不靠缺陷。** 真人感来自皮肤纹理、毛发细节、布料质感与光影，
> 不是来自一颗痣。

---

## 二、五步取词（写任何一条资产提示词都走这五步）

| 步 | 做什么 | 落在哪 |
|---|---|---|
| 1 | 定资产类型，打开对应槽位顺序表（第三节） | 选槽 |
| 2 | 按顺序逐槽取 **1** 个词条，人物填满 14–17 个槽（别填无关槽，见配额） | 取词 |
| 3 | 把词条**扩写成句子**（加方位、加材质因果、加数量），不直接罗列逗号串 | 成句 |
| 4 | 补**质感** 2–3 条（`realism`，正面写法）+ 光一句 + 镜头一句 | 落地 |
| 5 | 通读：字数够 500？没有互斥词？没有丑化词？没有空词？ | 自检 |

> 词条是**半成品**：`high cheekbones and a defined jawline` 要变成
> `High cheekbones and a defined jawline give the face a clean, angular read across the upper-left of the sheet.`

---

## 三、槽位顺序（顺序即句子顺序，别乱）

### 3.1 人物（18 槽，挑 14–17；**这就是 500 词的来源**）

`age → look → face → eyes → brows_nose → lips → skin → hair_len → hair_tex → hair_color → build → top → bottom → fabric_detail → accessory → hands → expression`

- **默认必写的 13 槽**：age、look、face、eyes、brows_nose、lips、skin、hair（长/质/色三槽）、build、
  top、bottom（或连衣裙）、fabric_detail、expression。少一槽就少 30–40 词，脸也会飘。
- **按人设取舍**：accessory（设定里没有就写 `no jewellery`）、hands（不拍手可省）。
- **剧情专用**：`worn`（衣服旧/脏）、`flaw`（脸上的痣疤伤）—— 见第一节第 4 条。
- 顺序的道理：**先骨相后皮肉，先本体后衣着**——模型先立结构，再贴细节，不容易糊。

### 3.2 场景（10 槽，挑 9–10）

`location → time → weather → structure → surfaces → furnishing → worn → light → color → air`

- **默认必写的 8 槽**：location、time、structure、surfaces、furnishing、worn、light、color；
  `weather` / `air` 按戏加。`worn`（水渍、烫痕、积灰、地面磨白）**默认写** —— 场景的"有人住过"靠它，
  而且不涉及把人写丑。
- `light` **单独一句**，来源 + 方向 + 质地 + 落点，一句写完。

### 3.3 道具（8 槽，全用）

`object → material → craft → size → finish → worn → marks → light`

- `size` 一定要给参照物（`no longer than a palm`）。
- `worn` / `marks` 道具默认可以写（旧物才有说服力，也不涉及人物美丑），但只取 1–2 条。
- **不写能读的品牌名**（等于让模型画文字，必糊），只写"磨花的刻字"。

---

## 四、配额（字数不够就是没写细）

| 资产 | 槽数 | 英文词数 | 备注 |
|---|---|---|---|
| 人物 | 14–17 / 18 | **≥ 500（500–700 最佳）** | 配饰 ≤3 件；质感 2–3 条；`flaw` 最多 1 条且必须有剧情依据 |
| 场景 | 9–10 / 10 | **≥ 500（500–700 最佳）** | 陈设 3–5 件、痕迹 2–3 条、光 1 句 |
| 道具 | 8 / 8 | 400–600 | 痕迹 1–2 条、特征细节 1–2 条 |

**字数怎么来的**：不是把形容词堆到 500 词，而是**每个槽都扩成一句**（1 槽 ≈ 25–40 词）。
18 个槽写满，自然就 500 词以上；写到 500 词还觉得空，说明槽没写够，不是字不够。

**判断标准**：删掉某个词条，这张图会不一样吗？不会 → 删掉。

---

## 五、质感不是瑕疵（这一节最容易写歪）

**要写**（`global.realism`，每类资产 2–3 条）：

1. 皮肤：`skin with a natural, even texture and a soft healthy sheen` /
   `a light beauty-filter finish that leaves the skin texture intact` /
   `a light, dewy highlight along the cheekbone`
2. 毛发：`fine vellus hair catching the light along the jaw` / 发丝分明的发束、干净的发际线
3. 材质：`fabric with a crisp hand and a clean edge` / `a soft natural sheen where the fabric folds` /
   `surfaces with an honest material grain, clean and well kept`
4. 光：一束明确的主光 + 一处柔和的补光，让人有体积

**不要写**（这些是"丑"，不是"真"）：

| 禁用写法 | 为什么 |
|---|---|
| `visible pores` / `毛孔清晰可见` / `no retouching` / `unretouched` | 反美颜词，直接把人做旧做糙 |
| `dry, chapped lips` / 嘴唇干裂 | 观众第一眼就出戏 |
| `messy hair` / `tousled` / 碎发散落、凌乱 | 除非剧情是刚起床 / 刚打完 |
| `wrinkled` / `creased` / 皱巴巴 | 除非剧情是逃难、住了三天旅馆 |
| 痣 / 疤 / 伤口 / 痘印 / 胎记 / 黑眼圈 / 油光 / 晒伤 | 只有剧本写了才写，且只写 1 条 |
| 主角衣服起球 / 污渍 / 磨边 | 主角按"体面"写，旧是配角与环境的信息 |

> 用户口径（见 03 的 4.1.1）：**真人质感 + 明确美颜**。毛孔绒毛不是不能提，但必须和
> `beauty filter` / `even tone` / `luminous` 写在同一句里，而且**不许出现"无修图"**这种反向指令。

---

## 六、正例（每类一条，都是压缩示例，实际按 500 词配额展开）

**人物**

> A photographic character reference sheet of a woman in her early thirties, East Asian features.
> A balanced oval face with high cheekbones and a softly defined jawline; almond-shaped dark brown eyes with a visible catchlight; straight natural brows; a straight nose with a rounded tip; a full upper lip with a defined cupid's bow, wearing a muted rose lip tint.
> A warm light-olive skin tone with a natural, even texture and a soft healthy sheen, a light beauty-filter finish that leaves the grain intact, fine vellus hair catching the light along the jaw.
> Shoulder-length hair, straight and fine, parted on the left and tucked behind one ear, natural black with a cool sheen.
> A slender hourglass silhouette — a naturally full bust, a softly narrowed waist, a gently rounded hip line — with graceful posture, shoulders back and weight settled on one leg.
> A cream ribbed knit top tucked into high-waisted tailored trousers in deep charcoal, a slim leather belt marking the waist; the knit has a crisp hand and a soft natural sheen where it folds.
> A thin silver chain at the throat and small pearl studs. Long fingers, short neat nails.
> A calm, composed expression, a level steady gaze into the lens. Against a plain seamless light-grey studio background.
> Shot on an 85mm prime lens at eye level, shallow depth of field, the face fully in focus. No text, no watermark, no CGI look.

**场景**

> A photographic interior of a cramped old-style interrogation room, deep night, rain just stopped and everything wet.
> A single high window with frosted glass and a floor drain with a rusted grate; walls of painted brick with the paint blistering at the lower third, an oiled hardwood floor worn pale along the centre, a ceiling of bare joists.
> A metal table bolted to the floor in the middle of the frame, a chair with one broken slat pushed back from it, a wall clock stopped at ten past two high on the right wall, three cardboard boxes stacked in the far corner.
> Water stains spreading from the ceiling corner, dust in every seam and on the window ledge, cigarette burns along the table edge.
> Light from a single bare bulb overhead, hard, throwing deep shadows under the table and a hard-edged pool of light on the floor; dust visible in the beam.
> A muted palette of grey, dirty white and rust. Shot on a 35mm lens at chest height, deep focus from the front edge to the far wall. No people, no text, no watermark.

**道具**

> A photographic still life of a folding pocket knife with a worn wooden handle, a cast iron blade housing with a pitted surface, hand-forged with hammer marks still visible along the spine.
> No longer than a palm. A dull patina over the whole surface, the edges rounded by handling, a deep scratch across the right face, an engraved initial worn almost smooth near the pivot.
> Hard direct light from the upper left with a single sharp highlight along the top edge, soft falloff into the background.
> On a matte dark-grey surface, the background falling off to black. Shot on a 100mm macro lens, flat field. No hands, no text, no watermark.

---

## 七、反例对照

| 写法 | 问题 | 改成 |
|---|---|---|
| `beautiful woman, gorgeous, stunning` | 空词，零信息 | `a balanced oval face with high cheekbones` |
| `左眼角下方有一颗小痣` / `a small mole under the eye`（剧本没提） | 画蛇添足，写丑，还会破坏后续镜头的人物一致性 | 删掉；要"有特点"就写骨相与五官结构 |
| `嘴唇微微干裂`、`皮肤毛孔清晰可见，无修图` | 直接把人做旧 | `a soft healthy sheen` + `a light beauty-filter finish` |
| `低马尾有些凌乱，碎发散落`（剧本没提） | 邋遢感 | `a low ponytail, neatly tied, a clean hairline` |
| `皱巴巴的白色 T 恤`（主角） | 廉价感 | `a crisp white cotton tee, freshly pressed` |
| `long straight black hair, short hair` | 互斥槽同时出现 | 只留一个 |
| `wearing a nice dress` | 没材质没版型 | `a knee-length A-line dress in crinkled silk` |
| `a room with furniture` | 没结构没痕迹 | `walls of painted brick with blistering paint, a metal table bolted to the floor` |
| `she looks sad and scared` | 资产图不演戏 | `a calm, composed expression, a level steady gaze` |
| 同一资产写两段提示词 | 细节互相污染 | 合成一条 |
| 人物提示词 200 词就收工 | 细节不足，脸必飘 | 按 14–17 槽写满，≥500 词 |

---

## 八、写完自检（连同 03 第七节一起过）

- [ ] 只出了**一条**？没有备选段落？
- [ ] **人物 / 场景 ≥500 词**（道具 400–600）？不是靠形容词凑的，是槽写满了？
- [ ] 每个槽只出现一次？没有互斥（长发/短发、素颜/浓妆、干净/脏污）？
- [ ] **没有丑化词**：痣 / 疤 / 伤口 / 痘印 / 干裂 / 凌乱 / 皱巴巴 / 污渍 / 油光 / 无修图？
      如果有，剧本里写了吗？`assets[].note` 记了吗？
- [ ] 质感写了吗（皮肤光泽 + 毛发细节 + 布料材质 + 一处高光）？
- [ ] 人物没写动作/场景/光位？场景没写人？道具没写手？
- [ ] 收尾有镜头一句 + 画质/禁止项一句？

---

## 九、附录：一条完整的人物提示词（约 580 词，照着这个密度写）

这就是"人物 ≥500 词"该有的样子：18 个槽按顺序填满、每个槽扩成句、**通篇没有一处丑化**。

> A photographic character reference sheet of a woman in her early thirties, East Asian features,
> read as one continuous design against a plain seamless light-grey studio background.
> A balanced oval face with high cheekbones and a softly defined jawline; the forehead is clear and the chin is
> gently rounded, which gives the whole face a composed, open shape across the upper-left third of the sheet.
> Almond-shaped dark brown eyes with a clear catchlight sit under straight natural brows that taper softly at the
> tails; a straight nose with a rounded tip runs down the centre line, and a full upper lip with a defined cupid's
> bow closes over a mouth whose corners lift only slightly.
> Her skin is a warm light-olive tone with a natural, even texture and a soft healthy sheen along the cheekbones,
> finished with a light beauty-filter finish that leaves the grain of the skin intact; fine vellus hair catches
> the light along the jaw and at the temples, and a light, dewy highlight sits on the high point of each cheek.
> Shoulder-length hair, straight and fine, parted on the left and tucked behind one ear so that the line of the
> jaw stays open; the colour is natural black with a cool sheen that picks up a narrow highlight along the crown,
> and the cut is fresh, with a clean hairline and evenly trimmed ends.
> The build is a slender hourglass silhouette — a naturally full bust, a softly narrowed waist and a gently
> rounded hip and thigh line — held in a graceful posture, shoulders back, spine long, the weight settled on one
> leg so the hip lifts slightly.
> She wears a cream ribbed knit top with a fine-gauge hand, tucked into high-waisted tailored trousers in deep
> charcoal; a slim leather belt in dark tan marks the waist, and the knit follows the bust and the waist before
> falling cleanly away over the hip. The trousers are pressed to a soft crease down the front, the leather has a
> matte finish with a narrow natural sheen along the edge, and the fabric across the shoulder carries a soft
> natural sheen where it folds.
> A thin silver chain sits at the throat and a pair of small pearl studs are set in each ear; there is no other
> jewellery, so the neckline stays clean.
> The hands are long-fingered with short, neat nails and a soft natural sheen across the knuckles.
> Her expression is calm and composed, the mouth closed and relaxed, the gaze level and steady into the lens,
> with the faintest lift at one brow that keeps the face from reading as blank.
> A single soft light from the upper left wraps the face, falling off gently toward the right cheek and leaving a
> soft shadow under the jaw and along the right side of the collar, while a weak fill from the background keeps
> the shadow side readable rather than black; a narrow rim of light traces the shoulder and the edge of the hair.
> The overall composition balances a large face study on the left against a full standing figure in the centre and
> a back view on the right, the three views sharing one light direction and one colour temperature throughout,
> with a restrained palette of warm ivory, deep charcoal and a single note of dark tan. Shot on an 85mm prime lens
> at eye level, shallow depth of field, the face fully in focus. No text, no watermark, no logo, no CGI look.

自检这条：18 槽用到 16 槽；主色三色（ivory / charcoal / dark tan）；质感 3 条（皮肤光泽、绒毛、布料）；
**丑化词 0 处**；每个槽都扩成了带方位的句子；词数约 580。
