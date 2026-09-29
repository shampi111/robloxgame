-- Атмосфера на клиенте: мигающие лампы, вращающиеся ключи, туман по локациям
-- и «страх» — чем ближе монстр, тем бледнее картинка, сильнее пульс и дрожь камеры.
local CollectionService = game:GetService("CollectionService")
local Lighting = game:GetService("Lighting")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local SoundService = game:GetService("SoundService")
local TweenService = game:GetService("TweenService")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"))

local player = Players.LocalPlayer
local random = Random.new()

-- Учёт деталей с тегом: registry[part] = данные из onAdded.
local function track(tag, onAdded)
	local registry = {}
	local function add(instance)
		registry[instance] = onAdded(instance)
	end
	CollectionService:GetInstanceAddedSignal(tag):Connect(add)
	CollectionService:GetInstanceRemovedSignal(tag):Connect(function(instance)
		registry[instance] = nil
	end)
	for _, instance in CollectionService:GetTagged(tag) do
		add(instance)
	end
	return registry
end

local flickerLamps = track("FlickerLight", function(lamp)
	return {
		light = lamp:FindFirstChildWhichIsA("Light"),
		color = lamp.Color,
		on = true,
		nextSwitch = os.clock() + random:NextNumber(0.5, 4),
	}
end)
local spinning = track("Spin", function(part)
	return part.CFrame
end)
local monsters = track("Monster", function()
	return true
end)

-- Туман и освещение для каждой локации (меняются только у этого игрока).
local ZONE_LIGHTING = {
	Maze = { FogColor = Color3.new(0, 0, 0), FogEnd = 80, OutdoorAmbient = Color3.new(0, 0, 0) },
	Forest = {
		FogColor = Color3.fromRGB(8, 10, 14),
		FogEnd = 70,
		OutdoorAmbient = Color3.fromRGB(16, 18, 26),
	},
	Lobby = { FogColor = Color3.new(0, 0, 0), FogEnd = 120, OutdoorAmbient = Color3.new(0, 0, 0) },
}
local function applyZoneLighting()
	local zone = if player:GetAttribute("InRound") then player:GetAttribute("Zone") else "Lobby"
	TweenService:Create(Lighting, TweenInfo.new(2), ZONE_LIGHTING[zone] or ZONE_LIGHTING.Lobby):Play()
end
player:GetAttributeChangedSignal("Zone"):Connect(applyZoneLighting)
player:GetAttributeChangedSignal("InRound"):Connect(applyZoneLighting)
applyZoneLighting()

local colorCorrection = Instance.new("ColorCorrectionEffect")
colorCorrection.Name = "Fear"
colorCorrection.Parent = Lighting
local blur = Instance.new("BlurEffect")
blur.Name = "FearBlur"
blur.Size = 0
blur.Parent = Lighting

-- Звуки (только если id заданы в Config.Sounds). Громкость меняется плавно.
local function loopSound(name)
	local id = Config.Sounds[name]
	if id == "" then
		return nil
	end
	local sound = Instance.new("Sound")
	sound.SoundId = id
	sound.Looped = true
	sound.Volume = 0
	sound.Parent = SoundService
	sound:Play()
	return sound
end
local sounds = {
	Ambience = loopSound("Ambience"),
	ForestAmbience = loopSound("ForestAmbience"),
	Chase = loopSound("Chase"),
	Heartbeat = loopSound("Heartbeat"),
}
local function fadeSound(name, target, dt)
	local sound = sounds[name]
	if sound then
		sound.Volume += (target - sound.Volume) * math.min(1, dt * 2)
	end
end

local fear = 0
local heartbeatPhase = 0

-- Ближайший монстр (подвальный или Тень) и гонится ли он.
local function nearestMonster(position)
	local best, chasing = math.huge, false
	for model in monsters do
		local root = model.PrimaryPart
		if root and model:IsDescendantOf(Workspace) then
			local distance = (root.Position - position).Magnitude
			if distance < best then
				best, chasing = distance, model:GetAttribute("Chasing") == true
			end
		end
	end
	return best, chasing
end

RunService.RenderStepped:Connect(function(dt)
	local now = os.clock()

	for lamp, data in flickerLamps do
		if now >= data.nextSwitch then
			data.on = not data.on
			data.nextSwitch = now + if data.on then random:NextNumber(0.8, 5) else random:NextNumber(0.05, 0.35)
			if data.light then
				data.light.Enabled = data.on
			end
			lamp.Material = if data.on then Enum.Material.Neon else Enum.Material.SmoothPlastic
			lamp.Color = if data.on then data.color else Config.Colors.LampOff
		end
	end

	local t = Workspace:GetServerTimeNow()
	for part, origin in spinning do
		part.CFrame = origin * CFrame.new(0, math.sin(t * 2) * 0.25, 0) * CFrame.Angles(0, t * 2, 0)
	end

	-- Страх: 0 — монстра нет рядом, 1 — он вплотную.
	local character = player.Character
	local root = character and character:FindFirstChild("HumanoidRootPart")
	local inRound = player:GetAttribute("InRound") == true
	local target, chasing = 0, false
	if root and inRound then
		local distance
		distance, chasing = nearestMonster(root.Position)
		target = math.clamp(1 - (distance - 8) / 60, 0, 1)
	end
	fear += (target - fear) * math.min(1, dt * 3)
	player:SetAttribute("Fear", fear)

	heartbeatPhase += dt * (1.2 + fear * 2.5) * math.pi * 2
	local beat = ((math.sin(heartbeatPhase) + 1) / 2) ^ 8 * fear
	colorCorrection.Saturation = -0.25 - fear * 0.6
	colorCorrection.Contrast = 0.1 + fear * 0.3
	colorCorrection.TintColor = Color3.new(1, 1 - beat * 0.35, 1 - beat * 0.35)
	blur.Size = fear * 3 + beat * 4

	local zone = player:GetAttribute("Zone")
	fadeSound("Ambience", if inRound and zone == "Maze" then 0.5 else 0, dt)
	fadeSound("ForestAmbience", if inRound and zone == "Forest" then 0.5 else 0, dt)
	fadeSound("Chase", if chasing and fear > 0.3 then 0.8 else 0, dt)
	fadeSound("Heartbeat", fear, dt)
end)

-- Дрожь камеры, когда монстр совсем близко (после обновления камеры).
RunService:BindToRenderStep("FearShake", Enum.RenderPriority.Camera.Value + 2, function()
	if fear > 0.6 then
		local strength = (fear - 0.6) * 0.02
		local camera = Workspace.CurrentCamera
		camera.CFrame *= CFrame.Angles(
			random:NextNumber(-strength, strength),
			random:NextNumber(-strength, strength),
			0
		)
	end
end)
