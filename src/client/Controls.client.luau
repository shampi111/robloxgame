-- Управление: фонарь (F) и бег (Shift) с выносливостью.
-- Фонарь светит туда, куда смотрит камера, и мигает, когда рядом монстр.
local ContextActionService = game:GetService("ContextActionService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local SoundService = game:GetService("SoundService")
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
ContextActionService:BindAction("ToggleFlashlight", function(_, inputState)
	if inputState == Enum.UserInputState.Begin then
		flashlightOn = not flashlightOn
		if clickSound then
			clickSound:Play()
		end
	end
	return Enum.ContextActionResult.Sink
end, true, Enum.KeyCode.F, Enum.KeyCode.ButtonY)
ContextActionService:SetTitle("ToggleFlashlight", "Фонарь")

local wantsSprint = false
ContextActionService:BindAction("Sprint", function(_, inputState)
	wantsSprint = inputState == Enum.UserInputState.Begin
	return Enum.ContextActionResult.Pass
end, true, Enum.KeyCode.LeftShift, Enum.KeyCode.ButtonL3)
ContextActionService:SetTitle("Sprint", "Бег")

local stamina = Config.StaminaMax
local exhausted = false
local lastSprint = 0
local sprinting = false

RunService.Heartbeat:Connect(function(dt)
	local character = player.Character
	local humanoid = character and character:FindFirstChildOfClass("Humanoid")
	local moving = humanoid ~= nil and humanoid.MoveDirection.Magnitude > 0.1
	sprinting = wantsSprint and moving and not exhausted

	if sprinting then
		stamina = math.max(0, stamina - Config.StaminaDrain * dt)
		lastSprint = os.clock()
		if stamina <= 0 then
			exhausted = true
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
