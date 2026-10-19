# 03 · Qwen-Image 2.1 资产提示词（融合 qwen-image-2.1-skill）

资产图全部由本地 **Qwen-Image 2.1** 生成。从 v2.1 起，资产提示词**不再写成中文逗号串**，改成
**一段英文、400 词左右、以"观察者描述画面"的口吻**写成的完整段落——这是 Qwen-Image-2.1 官方改写规范
（原技能 `qwen-image-2-1-prompter`）的要求，也是本技能资产质量的唯一来源。

> 权威细则：`references/qwen-t2i-rules.md`（八步框架原文）
> 词汇表：`references/qwen-cheat-sheet.md`（材质 / 方位 / 光照 / 比例）
> 改图（上传替换、局部重绘、多图合成）：`references/qwen-edit-rules.md`

---

## 一、两条路线，先分清楚

| 场景 | 模式 | 用哪份规则 |
|---|---|---|
| 新建资产定设图（人物 / 场景 / 道具） | **T2I** | `qwen-t2i-rules.md` + 本文件 |
| 用户上传图让你改、换背景、局部重绘、多图合成 | **Edit** | `qwen-edit-rules.md` |

本技能的 `assets[].prompt` **永远是 T2I 口吻**。Edit 只在人上传图替换或临时改图时才用，不写进 `drama.json` 的 `prompt` 字段。

---

## 二、八步框架（写每条资产提示词都走一遍）

1. **拆需求**：哪些是定死的（人名/物件/颜色/数量/位置），哪些要你补。短需求 ≠ 短描述，缺的要补满。
2. **定画幅**：比例只写进 `assets[].ratio`（人物 4:3、场景 16:9、道具 1:1），**正文里一个字都不许提比例和像素**（人物视图模板除外，那份模板由人在工作台维护）。
3. **开场句**：一句话约 20 词，交代「竖幅/横幅 + 媒介 + 主体 + 背景与色调」，媒介词绝不能省。
   > A vertical photographic character sheet of a 25-year-old Chinese woman, against a plain white studio background.
4. **列清单**：先在心里列两张单子——**方位清单**（画面里每样东西在哪个位置）和**文字清单**（画面上要出现的字，本技能一般没有）。
5. **走画面**：按区域或按主体顺序走一遍，句子里要出现 **8–14 个方位短语**（upper-left corner / across the top / along the lower third / in the centre…），必须铺到四角与边缘，不许全挤在中间。
6. **写文字**：有字就逐条写清位置、字体、颜色和引号里的原文。**本技能的资产一律不含可读文字**，这一步通常是"说明那里没有字、只有磨花的图案"。
7. **光照单独一句**：光源类型 + 方向 + 质感 + 造成的亮部与阴影。
8. **收尾一句**：`The overall composition …`，概括平衡感、色调、风格与气质，**只写一句**。

---

## 三、五条硬禁令（违反了 Qwen 反而变糊）

| 禁止 | 原因 | 改成 |
|---|---|---|
| `8K`、`超高清`、`masterpiece`、`award-winning`、`highly detailed` | 空词，会挤掉真实描述 | 写光学事实：`35mm prime lens, shallow depth of field, a clear even skin tone` |
| 在正文里写比例 / 像素（`4:3`、`1024×768`） | 比例走参数，正文写会打架 | 只说竖幅/横幅/方幅 |
| 对模型下命令（`make sure`、`the AI should`、`请生成`） | 破坏观察者口吻 | 现在时、第三人称、陈述句 |
| 堆形容词（`very beautiful, stunning`） | 无效 | 换成结构性事实：`high cheekbones, a defined jawline, a soft hourglass curve`（痣不算美，见 4.1.1-B） |
| 只给名词不给材质 | 材质才是分辨度 | `brushed stainless steel` / `coarse linen` / `weathered teak` |

另外两条常被忽略：

- **色彩要带修饰语**：`deep navy`、`muted olive`、`warm terracotta`、`off-white`，不写裸色名。
- **能数就数**：`three, five, twelve`，不写 `several` / `various`。

---

## 四、三类资产怎么落到八步

### 4.1 人物（定设图，4:3 三段拼接）

人物提示词**只写本体**：骨相、五官、发型发色、瞳色、皮肤特征、体型、服装材质与搭配、配饰位置。
**不写**动作、情绪、场景、镜头、光位（那些属于 H3 视频提示词）。

生成器会自动在末尾追加拼接构图块（见第六节），所以正文只描述"这个人长什么样"，不要描述排版。

> 排版这一段现在是**项目级可改**的：工作台「资产」页「生图参数」里有一个「人物视图模板」长条框（只有一个中文框），
> 改完点「保存参数」即生效，只影响本项目；清空回落到 `drama.py` 里的内置默认。
> 中文改过之后送进模型的就是中文那版（Qwen-Image 2.1 认中文），AI 之后可以按原格式补一版英文并清掉 `edited` 标记。
> 默认模板把画面切成三块：**左=大幅脸部特写（锁脸用）、中=无头全身像（颈部平整截断，有上身有下身有脚）、
> 右=有头背面照（肩膀与左侧视图齐平）**。因此人物画布必须是 **4:3**，用 16:9 会让三段挤压变形。

### 4.1.1 人物口径：真人质感 + 明确美颜（硬性，用户钦定）

官方规范只管**怎么写**（观察者口吻、结构、字数、方位），完全不管人好不好看——关于人只有一句
「Build, posture, where they are looking, expression, hair, skin tone, and each garment with its colour and material」。
美丑、胖瘦、干不干净全在**内容层**。默认按下面这套写。

#### A. 皮肤：毛孔与绒毛保留，但必须带美颜滤镜

| 项 | 口径 |
|---|---|
| 必须保留 | `visible fine pores`、`fine vellus hair` —— 这是"真人"的锚，去掉就变塑料 |
| 必须加上 | `a light beauty-filter finish`、`an even luminous tone`、`a soft-focus highlight along the cheekbone` |
| 禁止（病态） | `dry patch`、`tired shadow under the eyes`、`blemish`、`redness`、`acne`、`uneven patch of stubble` |
| 禁止（旧损） | `pilled`、`scuffed`、`crush mark`、`frayed`、`worn`、`stained` |

标准句式（一句同时点到"真"与"美"，二者不互斥）：

> Her skin keeps **visible fine pores and fine vellus hair**, yet reads **smooth and luminous under a light beauty filter**, with an even tone from the forehead to the jaw.

#### B. 无来由的特征一律不写

痣、美人痣、纹身、疤痕、伤痕、胎记、歪牙、黑眼圈、油光、晒伤、红血丝、痘印 —— **默认不写**。
只有剧本/人设明确要求时才写，且必须记进 `assets[].note` 存证。模型对"一颗痣"极其敏感，写了必出，
还会破坏后续所有镜头的人物一致性。

#### C. 女性：柔和曲线，不是直板

四条缺一不可，少一条就出直板身材：

1. **轮廓**：`a slender hourglass silhouette`
2. **三处曲线**：`a naturally full bust` ＋ `a softly narrowed waist` ＋ `a gently rounded hip and thigh line`
3. **体态**：`graceful posture — shoulders back, spine long, weight settled on one leg`
4. **服装塑形**：`the fabric follows the bust and the waist and flares away over the hip`

全部正向堆叠。**不要**写 `not a straight figure` —— 否定句对扩散模型近乎无效。

#### D. 男性：帅而不油腻

1. **脸**：`a defined jawline, straight brows, a high nose bridge, clear eyes`（用骨相写帅）
2. **皮肤**：`a clear fresh complexion with an even tone and a light beauty-filter finish`；禁 `oil sheen`、`sunburn`、`redness`、`tan lines`
3. **发型**：`a neatly styled haircut with a healthy sheen and a clean hairline`；禁 `messy`、`bedhead`、`flyaway`
4. **胡须**：二选一 —— `clean-shaven` 或 `a precisely trimmed short beard`；禁 `uneven stubble`、`patchy`
5. **身形**：`a lean athletic build, broad shoulders tapering into a narrow waist, long legs`

#### E. 穿搭：层次 + 配色 + 面料质感

四要素，少一样衣服就"呆板"：

| 要素 | 写法 |
|---|---|
| 版型 | `tailored / fitted / structured / cropped at the waist / high-rise`。**禁**把 `oversized`、`baggy`、`loose` 当主版型——那是呆板直板的源头 |
| 层次 | 至少三层可见：内搭 → 外层 → 腰带/下装 → 鞋。例：`a black sweatshirt over a crisp white crew-neck tee, a slim leather belt marking the waist` |
| 配色 | 主色 + 辅色 + 一个点缀色，三色以内且要有明暗对比。禁全黑 / 全灰 / 全白的单调 |
| 面料 | 具体且细腻：`high-sheen satin`、`brushed cotton`、`fine-gauge knit`、`matte leather`、`crisp cotton twill` |

人物条目在第七节自检之外，再硬加三条：

- [ ] 同时出现 `visible fine pores` + `fine vellus hair` 与 `beauty filter` / `luminous` / `even tone`。
- [ ] 女性写了 bust / waist / hip 三处曲线与优雅体态；男性写了宽肩窄腰，且没有油腻、晒伤、邋遢发型。
- [ ] 没有无来由的痣 / 纹身 / 疤痕 / 伤痕；穿搭有层次、有配色对比、面料具体。

信息清单（写全，缺一项脸就飘）：人种 / 年龄段 / 脸型与骨相 / 五官细节 / 发型发色 / 瞳色 / 皮肤质感（毛孔绒毛＋美颜滤镜）/ 体型与曲线 / 体态 / 服装（层次＋版型＋材质＋配色）/ 配饰（写清位置）。

### 4.2 场景（16:9 全景）

分两段写进同一段落：**A 空间本体**（空间类型、结构、材质、年代感，拒绝"复古""高级感"这类虚词）+ **B 光照**（光源位置、色温、方向、大气）。末尾要有"给人物留位置"的构图说明。

### 4.3 道具（1:1 白底）

器物名 + 材质 + 尺寸感 + 颜色 + 使用痕迹 + 上面的图案（用"褪色到看不清的牡丹"这种描述，**不要写可读文字**）。

---

## 五、`meta.styleLock`（全剧唯一风格锚）

`styleLock` 会拼在每条资产提示词末尾，所以它也要按同一套语言与口吻写：**一句英文描述式**，不要空词、不要命令句。

> Photoreal domestic comedy shot on an ARRI Alexa 65 with a 50mm prime, soft late-afternoon window light at 5200K, skin that keeps fine pores and vellus hair under a light beauty-filter finish, polished hair and wardrobe, gentle film grain.

`styleLock` 会拼在**每条**资产末尾（人物、场景、道具都吃一遍），所以它必须一句话同时点到位：

- 要写 `visible fine pores / fine vellus hair`（真人锚）**和** `beauty-filter finish`（美颜）——两个一起写，缺一个就翻车：
  只有毛孔 → 脏；只有滤镜 → 塑料。
- **不许**出现 `no retouching`、`no beautification`、`no filter`、`raw skin`、`tired`、`worn` —— 这几个词会把"去美化"复制到每一张图上，
  是全片发脏的最大放大器（上一版就是这么坏掉的）。

**不要**写成「8K、超高清、电影感、拒绝 AI 完美脸」这种口号堆砌——否定句对扩散模型基本无效，要写成正向的画面事实。

---

## 六、生成器自动追加的构图块（不要自己重复写）

`drama.py` 按 `assets[].type` 自动追加，内容已按 Qwen 规范改成陈述句：

- **character**（可在工作台改）：4:3 专业影棚，浅灰白无缝纯色背景，三段拼接、光影色调统一；
  左=大幅脸部特写（锁脸）、中=无头全身像（颈部平整截断，有上身有下身有脚）、
  右=有头背面照（肩膀与左侧视图齐平）。
- **scene**：全景宽构图、完整空间、留白、预留放人物的空间。
- **prop**：纯白背景、单件居中、无人物无手部。

---

## 七、交付前自检（资产提示词）

- [ ] 英文单段，350–500 词，没有中文（专有名词除外）。
- [ ] 开场句点了媒介（photograph / character sheet / still-life…）。
- [ ] 正文里没有比例、像素、`8K`、`masterpiece`。
- [ ] 方位短语 8–14 个，铺到四角与边缘。
- [ ] 光照有独立一句。
- [ ] 结尾有且只有一句 `The overall composition …`。
- [ ] 人物没有写动作/背景/镜头/光位；场景没有写"复古/高级感"；道具没有可读文字。
- [ ] `ratio` 与 `megapixels` 在 `assets[]` 里给对（人物 **4:3**·2.0、场景 16:9·2.0、道具 1:1·2.0）。
      人物用 16:9 会把三段拼接压变形，`check` 会报（它按人物视图模板里写的比例核对）。
