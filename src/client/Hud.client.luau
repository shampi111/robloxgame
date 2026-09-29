-- Интерфейс: цель и таймер сверху, выносливость снизу, сообщения и скример.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local SoundService = game:GetService("SoundService")
local TweenService = game:GetService("TweenService")
local UserInputService = game:GetService("UserInputService")

local Config = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"))
local remotes = ReplicatedStorage:WaitForChild("Remotes")
local state = ReplicatedStorage:WaitForChild("GameState")

local player = Players.LocalPlayer
local FONT = Enum.Font.GothamBold

local TOAST_COLORS = {
	info = Color3.fromRGB(230, 230, 230),
	key = Config.Colors.Key,
	exit = Config.Colors.DoorOpen,
	escape = Config.Colors.DoorOpen,
	danger = Color3.fromRGB(255, 70, 60),
}

local function make(className, props, children)
	local instance = Instance.new(className)
	for key, value in props do
		instance[key] = value
	end
	for _, child in children or {} do
		child.Parent = instance
	end
	return instance
end

local function corner(radius)
	return make("UICorner", { CornerRadius = UDim.new(0, radius) })
end

local gui = make("ScreenGui", { Name = "Hud", ResetOnSpawn = false, ZIndexBehavior = Enum.ZIndexBehavior.Sibling })

local statusLabel = make("TextLabel", {
	AnchorPoint = Vector2.new(0.5, 0),
	Position = UDim2.new(0.5, 0, 0, 8),
	Size = UDim2.fromOffset(460, 40),
	BackgroundColor3 = Color3.new(0, 0, 0),
	BackgroundTransparency = 0.45,
	Font = FONT,
	TextSize = 20,
	TextColor3 = Color3.new(1, 1, 1),
	Text = "",
}, { corner(10) })
statusLabel.Parent = gui

local staminaFill = make("Frame", {
	Size = UDim2.fromScale(1, 1),
	BackgroundColor3 = Color3.fromRGB(235, 235, 235),
	BorderSizePixel = 0,
}, { corner(4) })
local staminaBar = make("Frame", {
	AnchorPoint = Vector2.new(0.5, 1),
	Position = UDim2.new(0.5, 0, 1, -24),
	Size = UDim2.fromOffset(240, 8),
	BackgroundColor3 = Color3.new(0, 0, 0),
	BackgroundTransparency = 0.5,
	BorderSizePixel = 0,
	Visible = false,
}, { corner(4), staminaFill })
staminaBar.Parent = gui

local hint = make("TextLabel", {
	AnchorPoint = Vector2.new(0, 1),
	Position = UDim2.new(0, 16, 1, -16),
	Size = UDim2.fromOffset(300, 20),
	BackgroundTransparency = 1,
	Font = FONT,
	TextSize = 14,
	TextXAlignment = Enum.TextXAlignment.Left,
	TextColor3 = Color3.fromRGB(170, 170, 170),
	Text = "F — фонарь · Shift — бег",
	-- на телефоне вместо клавиш есть кнопки
	Visible = UserInputService.KeyboardEnabled,
})
hint.Parent = gui

local toastScale = make("UIScale", { Scale = 1 })
local toast = make("TextLabel", {
	AnchorPoint = Vector2.new(0.5, 0.5),
	Position = UDim2.fromScale(0.5, 0.28),
	Size = UDim2.new(0.9, 0, 0, 50),
	BackgroundTransparency = 1,
	Font = Enum.Font.GothamBlack,
	TextSize = 30,
	TextWrapped = true,
	TextColor3 = Color3.new(1, 1, 1),
	TextStrokeTransparency = 1,
	TextTransparency = 1,
	Text = "",
}, { toastScale })
toast.Parent = gui

gui.Parent = player:WaitForChild("PlayerGui")

local function formatTime(seconds)
	return string.format("%02d:%02d", seconds // 60, seconds % 60)
end

local function objective()
	local zone = player:GetAttribute("Zone")
	if zone == "Forest" then
		return if state:GetAttribute("GeneratorOn")
			then "Ворота открыты — к машине!"
			else "Найдите генератор в лесу"
	end
	if state:GetAttribute("ExitOpen") then
		return "Выход открыт! Ищите дверь ВЫХОД"
	end
	return string.format(
		"Ключи: %d/%d",
		state:GetAttribute("KeysFound") or 0,
		state:GetAttribute("KeysTotal") or 0
	)
end

local function updateStatus()
	local phase = state:GetAttribute("Phase")
	local timeLeft = state:GetAttribute("TimeLeft") or 0
	if phase == "Intermission" then
		statusLabel.Text = "Раунд начнётся через " .. timeLeft
	elseif phase == "Playing" then
		if player:GetAttribute("InRound") then
			statusLabel.Text = objective() .. "   ·   " .. formatTime(timeLeft)
		else
			statusLabel.Text = "Идёт раунд " .. formatTime(timeLeft) .. " — ждите следующего"
		end
	elseif phase == "Ending" then
		statusLabel.Text = "Раунд окончен"
	else
		statusLabel.Text = "Ждём игроков..."
	end
end
state.AttributeChanged:Connect(updateStatus)
player.AttributeChanged:Connect(function(name)
	if name == "InRound" or name == "Zone" then
		updateStatus()
	end
end)
updateStatus()

RunService.RenderStepped:Connect(function()
	local stamina = player:GetAttribute("Stamina") or 1
	staminaBar.Visible = stamina < 0.999
	staminaFill.Size = UDim2.fromScale(stamina, 1)
	staminaFill.BackgroundColor3 = if player:GetAttribute("Exhausted")
		then Color3.fromRGB(200, 60, 50)
		else Color3.fromRGB(235, 235, 235)
end)

local toastToken = 0
local function showToast(text, kind)
	toastToken += 1
	local token = toastToken
	toast.Text = text
	toast.TextColor3 = TOAST_COLORS[kind] or TOAST_COLORS.info
	toast.TextTransparency = 0
	toast.TextStrokeTransparency = 0.4
	toastScale.Scale = 0.7
	TweenService:Create(toastScale, TweenInfo.new(0.25, Enum.EasingStyle.Back), { Scale = 1 }):Play()
	task.delay(if kind == "danger" then 4 else 3, function()
		if token == toastToken then
			TweenService:Create(toast, TweenInfo.new(0.6), { TextTransparency = 1, TextStrokeTransparency = 1 }):Play()
		end
	end)
end
remotes:WaitForChild("Notify").OnClientEvent:Connect(showToast)

-- Скример: лицо во весь экран, тряска и вспышки. Собрано из рамок, без картинок.
local SCARE_EYES = {
	Monster = Config.Colors.MonsterEyes,
	Shadow = Config.Colors.ShadowEyes,
}
local scareGui = make("ScreenGui", {
	Name = "Jumpscare",
	ResetOnSpawn = false,
	IgnoreGuiInset = true,
	DisplayOrder = 100,
})
scareGui.Parent = player.PlayerGui

local scareSound
if Config.Sounds.Jumpscare ~= "" then
	scareSound = make("Sound", { SoundId = Config.Sounds.Jumpscare, Volume = 2 })
	scareSound.Parent = SoundService
end

local function jumpscare(kind)
	local eyeColor = SCARE_EYES[kind] or SCARE_EYES.Monster
	local background = make("Frame", {
		Size = UDim2.fromScale(1, 1),
		BackgroundColor3 = Color3.new(0, 0, 0),
		BorderSizePixel = 0,
	})
	local scale = make("UIScale", { Scale = 0.3 })
	local face = make("Frame", {
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.5),
		Size = UDim2.fromScale(0.8, 0.8),
		BackgroundTransparency = 1,
	}, { make("UIAspectRatioConstraint", { AspectRatio = 1 }), scale })
	for _, x in { 0.3, 0.7 } do
		make("Frame", {
			AnchorPoint = Vector2.new(0.5, 0.5),
			Position = UDim2.fromScale(x, 0.36),
			Size = UDim2.fromScale(0.2, 0.13),
			BackgroundColor3 = eyeColor,
			Rotation = if x < 0.5 then 12 else -12,
			Parent = face,
		}, {
			make("UICorner", { CornerRadius = UDim.new(0.5, 0) }),
			make("UIStroke", { Color = eyeColor, Thickness = 10, Transparency = 0.5 }),
			make("Frame", {
				AnchorPoint = Vector2.new(0.5, 0.5),
				Position = UDim2.fromScale(0.5, 0.5),
				Size = UDim2.fromScale(0.14, 0.9),
				BackgroundColor3 = Color3.new(0, 0, 0),
			}, { make("UICorner", { CornerRadius = UDim.new(0.5, 0) }) }),
		})
	end
	-- Рот с зубами: ряды повёрнутых квадратиков сверху и снизу.
	local mouth = make("Frame", {
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.72),
		Size = UDim2.fromScale(0.62, 0.2),
		BackgroundColor3 = Color3.fromRGB(40, 0, 0),
		ClipsDescendants = true,
		Parent = face,
	}, { make("UICorner", { CornerRadius = UDim.new(0.4, 0) }) })
	for i = 0, 9 do
		for _, y in { 0, 1 } do
			make("Frame", {
				AnchorPoint = Vector2.new(0.5, 0.5),
				Position = UDim2.fromScale((i + 0.5) / 10, y),
				Size = UDim2.fromScale(0.09, 0.45),
				SizeConstraint = Enum.SizeConstraint.RelativeXX,
				Rotation = 45,
				BackgroundColor3 = Color3.fromRGB(230, 225, 205),
				BorderSizePixel = 0,
				Parent = mouth,
			})
		end
	end
	face.Parent = background
	background.Parent = scareGui

	if scareSound then
		scareSound:Play()
	end
	TweenService:Create(scale, TweenInfo.new(0.12, Enum.EasingStyle.Quad), { Scale = 1.15 }):Play()
	local started = os.clock()
	while os.clock() - started < 1.1 do
		face.Position = UDim2.new(0.5, math.random(-25, 25), 0.5, math.random(-25, 25))
		background.BackgroundColor3 = if math.random() < 0.3 then Color3.fromRGB(70, 0, 0) else Color3.new(0, 0, 0)
		task.wait(0.03)
	end
	face:Destroy()
	background.BackgroundColor3 = Color3.new(0, 0, 0)
	local fade = TweenService:Create(background, TweenInfo.new(1.5), { BackgroundTransparency = 1 })
	fade:Play()
	fade.Completed:Wait()
	background:Destroy()
end
remotes:WaitForChild("Jumpscare").OnClientEvent:Connect(jumpscare)
