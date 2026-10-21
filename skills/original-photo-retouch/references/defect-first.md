# 缺陷诊断先于参考

先用模型实际看图，再用程序校验证据。程序不能判断“这是污点还是主体”，生成图也不能证明原片缺陷存在。每张新改照片先保存 `schema_version:1, method:chatgpt_vision` 的诊断：`source.path/sha256`、`diagnosed_at`、`subject`、`visual_hierarchy`、`observed_key_light`、`views_actually_reviewed`、`defects`。每个缺陷包含 `id, observation, location, classification, decision, reason, reference_instruction, acceptance`。决定限 `repair/crop/tone/retain`，无缺陷明确写空列表。

参考生成后补充 `new_reference.path/sha256/generated_at/visual_comparison`，保持诊断在先。配方 `vision_preflight` 指向此文件；执行器核对原片、实看图、新参考哈希和时间次序。不能倒填诊断时间，不把复制文件的时间冒充观察时间，不能只写“更高级”“更通透”等不可验收目标。已有成片的保留决定记录本轮观察范围，细节证据沿用此前实际记录。

## 判断对象和处理方法

- 污点候选：尘影常是无语义弥散圆斑，同场同传感器位置重复可增强证据。孤立暗团可能是云、鸟或远物；先看原生局部。不要抹掉痣、毛孔、真实发丝、手指阴影或正常镜片受光。
- 场景玻璃反射：观察与真实地形不一致的漂浮轮廓、双影或遮罩状反射；必须区分真实山脊、云与景深软化。逐点记录真实结构保护边界，不靠“变清晰”掩盖双影。
- 构图干扰：近景动物仅剩半只或残翼时评估有限裁切或同片取样；完整陪体、连续山坡/海浪/木栏并不因触边就必须删除。裁切会切掉塔尖或压缩人像时优先评估可验证的局部修复。
- 光影：先描述主光、主体受光面、体积转折、投影、环境反光和视觉主次，再决定加光与压光；不以全局饱和度或统一阴影提升代替。

## 同片场景修复

`scene_patch` 用于已确认的 `glass_reflection` 或 `edge_distraction`。步骤先于新增光色调整，需要已验收标注的 `target_id/donor_id`，以及实际 `purpose/protected_structure/donor_review`。仅复制同一原片可见像素，整数平移，目标包围框≤15%画面，羽化≤150原生像素，取样连同羽化支持不得越界。可用独立减选轮廓保护真实山脊。`rgb_offset` 仅允许三个绝对值≤32的整数作小幅色调衔接，不能据此造纹理。不支持旋转、拉伸、外图纹理或生成填充。

整图先验收干扰是否消失，再看原生目标、取样和边界：亮线、糊块、重复纹理、噪声差异、山脊损失、人物改变任一明显存在均需迭代。只完成配方或执行成功仍是待验收。

## 光影塑造的实际反馈

宽光场与窄结构保护分开：宽渐变组织湖面/坡面主次，窄边界限制岸线或人物轮廓。先对照明度，再对照色彩和纹理。RGB曲线斜率直接影响局部对比；单通道陡折容易让水纹变平、偏紫或压死，不用它替代自然光路。先以明度混合和低幅宽柔加光控制主次，再小幅调色。每轮实看同文档指定塑光层开/关，记录切换范围；原生细节以1:1局部检查，不用缩览替代。

最终PSD须实际重开核对，最终JPEG须与通过视觉检查的工作样一致；脚本不自动宣布审美验收。原片失焦、高光剪切和生成参考新增的白浪、锐树雪不能冒充可恢复细节。

## 学习依据及适用边界

本轮实际读取以下文章，规则以本机原生工作样验证，不以教程措辞保证效果：

- [Cambridge：编辑工作流程](https://www.cambridgeincolour.com/tutorials/digital-photo-editing-workflow.htm)：先整理白平衡、曝光和对比，再做局部；保存修改副本，警惕过度色彩。
- [Cambridge：曲线](https://www.cambridgeincolour.com/tutorials/photoshop-curves.htm)：曲线斜率改变局部对比，压缩某些影调会牺牲结构。用于发现水面过陡单通道曲线的问题。
- [Cambridge：构图三分](https://www.cambridgeincolour.com/tutorials/rule-of-thirds.htm)：裁切用于调整主次，规则不是强制模板。
- [Tony Kuyper：明度蒙版](https://goodlight.us/writing/luminositymasks/luminositymasks-1.html)：按原像素明度生成连续选择。明度选择不等于主体识别，也不保证任意山脊边缘正确。

Adobe两页本轮返回403、旧Tony dodge/burn地址404，未作为已读依据；不为读取教程修改用户网络设置。
