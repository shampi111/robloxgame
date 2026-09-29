-- Тень — существо из леса. Появляется за спиной у игрока и подкрадывается,
-- пока на неё никто не смотрит. Под взглядом замирает, а если смотреть долго — исчезает.
-- Ходит сквозь деревья, поэтому двигается без физики (PivotTo).
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Workspace = game:GetService("Workspace")

local Config = require(ReplicatedStorage.Shared.Config)
local scare = require(script.Parent.Scare)

local SETTINGS = Config.Shadow
local TICK = 0.05
local PIVOT_HEIGHT = 5 -- высота корневой детали над землёй

local Shadow = {}
Shadow.__index = Shadow

local function flat(vector)
	return Vector3.new(vector.X, 0, vector.Z)
end

-- Очень высокая тонкая фигура с белыми глазами. Собрана вокруг точки у ног, смотрит на -Z.
local function buildModel()
	local model = Instance.new("Model")
	model.Name = "Shadow"
	model.ModelStreamingMode = Enum.ModelStreamingMode.Atomic

	local function part(name, size, cframe, props)
		local p = Instance.new("Part")
		p.Name = name
		p.Size = size
		p.CFrame = cframe
		p.Anchored = true
		p.CanCollide = false
		p.CanQuery = false
		p.CanTouch = false
		p.Color = Config.Colors.ShadowBody
		p.Material = Enum.Material.SmoothPlastic
		for key, value in props or {} do
			p[key] = value
		end
		p.Parent = model
		return p
	end

	local root = part("Root", Vector3.new(1, 1, 1), CFrame.new(0, PIVOT_HEIGHT, 0), { Transparency = 1 })
	part("LeftLeg", Vector3.new(0.5, 5.5, 0.5), CFrame.new(-0.4, 2.75, 0))
	part("RightLeg", Vector3.new(0.5, 5.5, 0.5), CFrame.new(0.4, 2.75, 0))
	part("Torso", Vector3.new(1.6, 3.8, 0.8), CFrame.new(0, 7.4, 0))
	part("LeftArm", Vector3.new(0.35, 6.5, 0.35), CFrame.new(-1.05, 6.2, 0) * CFrame.Angles(0, 0, math.rad(-5)))
	part("RightArm", Vector3.new(0.35, 6.5, 0.35), CFrame.new(1.05, 6.2, 0) * CFrame.Angles(0, 0, math.rad(5)))
	local head = part("Head", Vector3.new(1.2, 1.5, 1.2), CFrame.new(0, 10.1, 0))
	for _, x in { -0.28, 0.28 } do
		part("Eye", Vector3.new(0.22, 0.22, 0.05), CFrame.new(x, 10.3, -0.62), {
			Color = Config.Colors.ShadowEyes,
			Material = Enum.Material.Neon,
		})
	end

	model.PrimaryPart = root
	model:AddTag("Monster")
	return model, head
end

function Shadow.new(forest)
	local self = setmetatable({}, Shadow)
	self.forest = forest
	self.rng = Random.new()
	self.model, self.head = buildModel()
	self.visible = false
	self.position = Vector3.zero
	self.target = nil
	self.stare = 0
	self.reappearAt = 0

	self.rayParams = RaycastParams.new()
	self.rayParams.FilterType = Enum.RaycastFilterType.Include
	self.rayParams.FilterDescendantsInstances = { forest.trees }
	return self
end

function Shadow:start()
	self.running = true
	task.spawn(function()
		local last = os.clock()
		while self.running do
			local now = os.clock()
			self:step(now - last, now)
			last = now
			task.wait(TICK)
		end
	end)
end

function Shadow:destroy()
	self.running = false
	self.model:Destroy()
end

-- Живые игроки в лесу.
function Shadow:targets()
	local result = {}
	for _, player in Players:GetPlayers() do
		local character = player.Character
		local humanoid = character and character:FindFirstChildOfClass("Humanoid")
		local root = character and character:FindFirstChild("HumanoidRootPart")
		local inForest = player:GetAttribute("InRound") and player:GetAttribute("Zone") == "Forest"
		if inForest and humanoid and humanoid.Health > 0 and root then
			table.insert(result, { player = player, root = root, head = character:FindFirstChild("Head") or root })
		end
	end
	return result
end

function Shadow:place()
	local pivot = self.position + Vector3.new(0, PIVOT_HEIGHT, 0)
	local facing = self.target and flat(self.target.root.Position) + Vector3.new(0, PIVOT_HEIGHT, 0)
	if facing and (facing - pivot).Magnitude > 0.1 then
		self.model:PivotTo(CFrame.lookAt(pivot, facing))
	else
		self.model:PivotTo(CFrame.new(pivot))
	end
end

-- Появляется за спиной у игрока (distance стадов), в пределах леса.
function Shadow:appear(target, distance)
	local look = flat(target.root.CFrame.LookVector)
	local back = if look.Magnitude > 0.01 then -look.Unit else Vector3.new(0, 0, 1)
	local direction = CFrame.Angles(0, self.rng:NextNumber(-0.8, 0.8), 0):VectorToWorldSpace(back)
	local position = flat(target.root.Position) + direction * distance
	local forest = self.forest
	self.position = Vector3.new(
		math.clamp(position.X, forest.minX + 2, forest.gateX - 2),
		0,
		math.clamp(position.Z, forest.minZ + 2, forest.maxZ - 2)
	)
	self.target = target
	self.stare = 0
	self.visible = true
	self:place()
	self.model.Parent = forest.folder
	self.model:SetAttribute("Chasing", true)
end

function Shadow:hide(now)
	self.visible = false
	self.target = nil
	self.stare = 0
	self.model.Parent = nil
	self.reappearAt = now + SETTINGS.ReappearDelay * self.rng:NextNumber(0.7, 1.3)
end

-- Шум (например, запуск генератора) сразу приманивает Тень к игроку.
function Shadow:attract(player)
	for _, target in self:targets() do
		if target.player == player then
			self:appear(target, SETTINGS.AppearDistance * 0.7)
			return
		end
	end
end

-- Смотрит ли игрок на Тень: она в его поле зрения и её не закрывают деревья.
-- Направление взгляда берём от персонажа: в режиме от первого лица он повёрнут вслед за камерой.
function Shadow:isSeenBy(target)
	local toShadow = self.head.Position - target.head.Position
	local flatTo = flat(toShadow)
	local look = flat(target.root.CFrame.LookVector)
	if flatTo.Magnitude > SETTINGS.ViewDistance or flatTo.Magnitude < 0.1 or look.Magnitude < 0.01 then
		return false
	end
	if look.Unit:Dot(flatTo.Unit) < math.cos(math.rad(SETTINGS.ViewAngle)) then
		return false
	end
	return Workspace:Raycast(target.head.Position, toShadow, self.rayParams) == nil
end

function Shadow:step(dt, now)
	local targets = self:targets()
	if #targets == 0 then
		-- В лесу никого: прячемся и ждём, пока кто-нибудь выйдет из подвала.
		if self.visible then
			self:hide(now)
		end
		self.reappearAt = now + SETTINGS.ReappearDelay
		return
	end

	if not self.visible then
		if now >= self.reappearAt then
			self:appear(targets[self.rng:NextInteger(1, #targets)], SETTINGS.AppearDistance)
		end
		return
	end

	-- Жертва умерла, сбежала или вышла: выбираем ближайшего.
	local current
	for _, target in targets do
		if self.target and target.player == self.target.player then
			current = target
		end
	end
	if not current then
		local best = math.huge
		for _, target in targets do
			local distance = (flat(target.root.Position) - self.position).Magnitude
			if distance < best then
				current, best = target, distance
			end
		end
	end
	self.target = current

	local observed = false
	for _, target in targets do
		if self:isSeenBy(target) then
			observed = true
			break
		end
	end

	if observed then
		self.stare += dt
		if self.stare >= SETTINGS.StareTime then
			self:hide(now)
			return
		end
	else
		self.stare = math.max(0, self.stare - dt * 0.5)
		local offset = flat(current.root.Position) - self.position
		if offset.Magnitude > 0.1 then
			self.position += offset.Unit * math.min(offset.Magnitude, SETTINGS.Speed * dt)
		end
	end
	self:place()

	for _, target in targets do
		if (flat(target.root.Position) - self.position).Magnitude <= SETTINGS.CatchRange then
			scare(target.player, "Shadow")
			self:hide(now)
			return
		end
	end
end

return Shadow
