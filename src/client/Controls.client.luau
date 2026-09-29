-- Управление: фонарь (F) и бег (Shift) с выносливостью.
-- Фонарь светит туда, куда смотрит камера, и мигает, когда рядом монстр.
-- На телефоне — свои кнопки над кнопкой прыжка (бег там включается нажатием).
local ContextActionService = game:GetService("ContextActionService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local SoundService = game:GetService("SoundService")
local UserInputService = game:GetService("UserInputService")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"))

local player = Players.LocalPlayer
local FLASHLIGHT_OFFSET = CFrame.new(0.6, -0.5, -1.5) -- «в руке» чуть правее и ниже глаз
local BASE_FOV = 70
local SPRINT_FOV = 80

-- Фонарь — невидимая деталь только на этом клиенте, которую каждый кадр ставим к камере.
local rig = Instance.new("Part")
rig.Name = "Flashlight"
rig.Size = Vector3.new(0.2, 0.2, 0.2)
rig.Transparency = 1
rig.Anchored = true
rig.CanCollide = false
rig.CanQuery = false
rig.CanTouch = false
local light = Instance.new("SpotLight")
light.Face = Enum.NormalId.Front
light.Angle = 50
light.Range = 55
light.Brightness = 2.5
light.Shadows = true
light.Color = Color3.fromRGB(255, 244, 220)
light.Parent = rig
rig.Parent = Workspace

local clickSound
if Config.Sounds.Flashlight ~= "" then
	clickSound = Instance.new("Sound")
	clickSound.SoundId = Config.Sounds.Flashlight
	clickSound.Parent = SoundService
end

local flashlightOn = true
local function toggleFlashlight()
	flashlightOn = not flashlightOn
	if clickSound then
		clickSound:Play()
	end
end
ContextActionService:BindAction("ToggleFlashlight", function(_, inputState)
	if inputState == Enum.UserInputState.Begin then
		toggleFlashlight()
	end
	return Enum.ContextActionResult.Sink
end, false, Enum.KeyCode.F, Enum.KeyCode.ButtonY)

local sprintHeld = false -- Shift / L3 зажаты
local sprintToggled = false -- кнопка «Бег» на телефоне
ContextActionService:BindAction("Sprint", function(_, inputState)
	sprintHeld = inputState == Enum.UserInputState.Begin
	return Enum.ContextActionResult.Pass
end, false, Enum.KeyCode.LeftShift, Enum.KeyCode.ButtonL3)

-- Кнопки для сенсорного экрана. Стандартная кнопка прыжка Roblox стоит справа внизу:
-- на маленьких экранах её верх в 90 px от низа, на больших — в 210 px. Ставим свои кнопки
-- столбиком над ней, по той же вертикали.
local updateSprintButton = function() end
if UserInputService.TouchEnabled then
	local gui = Instance.new("ScreenGui")
	gui.Name = "MobileControls"
	gui.ResetOnSpawn = false

	local function makeButton(text)
		local button = Instance.new("TextButton")
		button.AnchorPoint = Vector2.new(0.5, 1)
		button.BackgroundColor3 = Color3.new(0, 0, 0)
		button.BackgroundTransparency = 0.45
		button.Font = Enum.Font.GothamBold
		button.TextColor3 = Color3.new(1, 1, 1)
		button.Text = text
		local corner = Instance.new("UICorner")
		corner.CornerRadius = UDim.new(0.5, 0)
		corner.Parent = button
		local stroke = Instance.new("UIStroke")
		stroke.ApplyStrokeMode = Enum.ApplyStrokeMode.Border
		stroke.Color = Color3.new(1, 1, 1)
		stroke.Transparency = 0.6
		stroke.Thickness = 2
		stroke.Parent = button
		button.Parent = gui
		return button
	end
	local flashButton = makeButton("Фонарь")
	local sprintButton = makeButton("Бег")

	local function layout()
		local screen = gui.AbsoluteSize
		local small = math.min(screen.X, screen.Y) <= 500
		local size = if small then 56 else 80
		local jumpTop = if small then 90 else 210 -- верх кнопки прыжка, px от низа
		local jumpCenter = if small then 60 else 110 -- центр кнопки прыжка, px от правого края
		local gap = if small then 10 else 14
		for index, button in { flashButton, sprintButton } do
			button.Size = UDim2.fromOffset(size, size)
			button.TextSize = if small then 12 else 16
			button.Position = UDim2.new(1, -jumpCenter, 1, -(jumpTop + gap + (index - 1) * (size + gap)))
		end
	end
	gui:GetPropertyChangedSignal("AbsoluteSize"):Connect(layout)

	updateSprintButton = function()
		sprintButton.BackgroundColor3 = if sprintToggled then Color3.fromRGB(200, 170, 60) else Color3.new(0, 0, 0)
	end
	flashButton.Activated:Connect(toggleFlashlight)
	sprintButton.Activated:Connect(function()
		sprintToggled = not sprintToggled
		updateSprintButton()
	end)

	gui.Parent = player:WaitForChild("PlayerGui")
	layout()
end

local stamina = Config.StaminaMax
local exhausted = false
local lastSprint = 0
local sprinting = false

RunService.Heartbeat:Connect(function(dt)
	local character = player.Character
	local humanoid = character and character:FindFirstChildOfClass("Humanoid")
	local moving = humanoid ~= nil and humanoid.MoveDirection.Magnitude > 0.1
	sprinting = (sprintHeld or sprintToggled) and moving and not exhausted

	if sprinting then
		stamina = math.max(0, stamina - Config.StaminaDrain * dt)
		lastSprint = os.clock()
		if stamina <= 0 then
			exhausted = true
			-- выдохся — кнопка бега на телефоне выключается
			sprintToggled = false
			updateSprintButton()
		end
	elseif os.clock() - lastSprint > Config.StaminaRegenDelay then
		stamina = math.min(Config.StaminaMax, stamina + Config.StaminaRegen * dt)
	end
	if exhausted and stamina >= Config.StaminaMax * Config.StaminaRecover then
		exhausted = false
	end

	if humanoid and humanoid.Health > 0 then
		humanoid.WalkSpeed = if sprinting then Config.SprintSpeed else Config.WalkSpeed
	end
	-- Атрибуты на своём игроке видны только этому клиенту — их читает интерфейс.
	player:SetAttribute("Stamina", stamina / Config.StaminaMax)
	player:SetAttribute("Exhausted", exhausted)
end)

RunService:BindToRenderStep("Flashlight", Enum.RenderPriority.Camera.Value + 1, function(dt)
	local camera = Workspace.CurrentCamera
	rig.CFrame = camera.CFrame * FLASHLIGHT_OFFSET

	-- Рядом монстр (атрибут Fear выставляет скрипт Atmosphere) — фонарь барахлит.
	local fear = player:GetAttribute("Fear") or 0
	local flicker = fear > 0.45 and math.random() < fear * 0.25
	light.Enabled = flashlightOn and not flicker

	local targetFov = if sprinting then SPRINT_FOV else BASE_FOV
	camera.FieldOfView += (targetFov - camera.FieldOfView) * math.min(1, dt * 8)
end)
