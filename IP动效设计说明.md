# 约定 v2.3：IP 与界面动效

保留三栏、六步流程和原有蓝白 IP。此次动效属于展示层，不调用模型，也不提交任务、采纳修改或批准定稿。

## 视觉与放置

- 左侧文件栏底部使用一个固定的 IP 工作陪伴区。原蓝色角色、机器人与金色天平保留，默认以低频眨眼配轻微悬浮呈现。
- AI 处理时，状态文字显示真实任务阶段，配合轻微轨道与状态点变化；任务成功后短暂显示完成反馈。失败展示任务原因提示，不显示庆祝。完成反馈不表示法务已经批准协议。
- 三栏背景、当前流程步骤、文件选中态、按钮和输入框采用淡蓝层次、柔和边框和轻量阴影。正文仍保持白底。
- 文档切换使用 220 毫秒的淡入；新 AI 回复短暂出现动画。既有回复不会在每次轮询时重复动画。

## 控制与性能

动效区右上角可暂停或恢复，偏好保存在当前浏览器。暂停时切换真正的静态 PNG，同时关闭界面过渡与循环动画。系统启用“减少动态效果”时自动使用静态版。隐藏页面、进入专注模式，以及手机文件栏关闭时，IP 切为静态图片。

状态轮询只更新工作陪伴区的状态及文字，不重建动图元素，避免每次查询进度时从头播放。手机文件栏沿用原抽屉模式，IP 在抽屉内，不遮挡中央协议或 AI 对话。

## 文件与制作方式

使用 **imagegen 内置工具**，以原 `public/assets/character-sheet.png` 为身份和材质参考，生成四帧眨眼图。生成原图另存，未覆盖旧 IP。随后用 Pillow 做帧切分、尺寸统一和动画格式编码；没有用第三方模型接口生成图片。

- `public/assets/companion-frames.png`：四帧生成原图。
- `public/assets/companion-idle.webp`：网页用透明动画，四帧，5.1 秒循环，约 160 KB。
- `public/assets/companion-still.png`：暂停、减少动态效果及隐藏状态用的静态版。
- `public/assets/companion-blink.gif`：独立 GIF，四帧，5.1 秒循环，约 225 KB；采用与陪伴区相近的浅色底。网页采用 WebP 保留透明柔边。
- `public/motion.js`、`public/motion.css`：独立展示层；后端只增加这些资源的明确访问白名单。

## 验证

浏览器验证了动图资源加载、六步流程保留、暂停和恢复、刷新后偏好、系统减少动态效果、专注模式、处理中状态、轮询保持动图节点、处理中暂停、失败不显示成功、手机抽屉及溢出、三轮示例聊天与完成反馈不推进法务步骤。完整示例流程复测通过。首次全流程运行的聊天等待曾超时，未形成聊天任务；已保留异常诊断，随后完整复测及连续三轮聊天通过，尚未复现该等待。

图片文件核验四帧、循环时长、透明图 alpha 和文件可解码性。本次 UI 回归未额外调用真实模型，未更新线上站点。本机服务为加载新资源重启，进程内的模型密钥需在“设置”里重新填写。

## 最终生成提示词

```text
Use case: stylized-concept. Asset type: 4-frame sprite sheet for the original 约定 legal AI workbench mascot, to be assembled into a small looping transparent GIF and WebP. Input image is a character identity and materials reference, not an edit target. Create a NEW precise 2 by 2 sprite sheet, four EQUAL square cells, no grid lines. Overall canvas 1024x1024, genuinely transparent background, no backdrop, no words or labels. Each cell shows the SAME original reference pair: glossy translucent cobalt and sky blue friendly curled-top water-drop ghost, white lower face, large dark blue sparkling oval eyes, tiny smile, rosy cheeks, small gold scales medallion floating above left shoulder; tiny white-and-blue floppy-ear robot companion at the mascot's lower right with a dark smiling face display and blue shield on chest. Keep proportions, color, materials and recognizability extremely close to reference, clean premium 3D render. Main mascot holds a small translucent blue legal document with 3 simple line marks, no text. Full bodies visible, small robot visible. Fixed front camera, same exact size, silhouette, body position, robot position, medallion position and floor level in every frame. Center each pair inside its cell, 12 percent safe empty transparent margin on all sides, the pair occupies 76 percent of cell height. The four frames are subtle facial animation only: top left eyes fully open friendly smile; top right eyelids half closed gentle blink; bottom left both eyes gently closed, same tiny smile; bottom right eyes fully open again, slightly warmer smile. Do not change the arm positions or costumes. No sparkles outside cell bounds, no stars, no extra character, no floating interface panels, no shadow ground, no white background. Crisp alpha edges suitable for white sidebar. This should feel like a quiet professional companion, not an energetic cartoon.
```

