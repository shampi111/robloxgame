-- Текстуры из Creator Store (id задаются в Config.Textures).
-- В ссылке на декаль стоит id самой декали, а детали нужен id картинки внутри неё,
-- поэтому декаль загружается через InsertService и из неё берётся Texture.
local InsertService = game:GetService("InsertService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage.Shared.Config)

local Textures = {}

local resolved = {} -- [имя] = content id картинки или false

local function resolveId(id)
	local ok, model = pcall(InsertService.LoadAsset, InsertService, id)
	if ok and model then
		local decal = model:FindFirstChildWhichIsA("Decal", true)
		local image = decal and decal.Texture
		model:Destroy()
		if image then
			return image
		end
	end
	-- Не декаль (или не загрузилась) — пробуем как id картинки.
	return "rbxassetid://" .. id
end

-- Загружает все текстуры из конфига. Вызывается один раз при запуске сервера.
function Textures.preload()
	for name, id in Config.Textures do
		resolved[name] = if type(id) == "number" and id > 0 then resolveId(id) else false
	end
end

function Textures.get(name)
	return resolved[name] or nil
end

-- Накладывает повторяющуюся текстуру на стороны детали. Ничего не делает, если id не задан.
function Textures.apply(part, name, faces)
	local image = Textures.get(name)
	if not image then
		return false
	end
	local tile = Config.TextureTiles[name] or 8
	for _, face in faces do
		local texture = Instance.new("Texture")
		texture.Texture = image
		texture.Face = face
		texture.StudsPerTileU = tile
		texture.StudsPerTileV = tile
		texture.Parent = part
	end
	return true
end

-- Одиночная декаль (плакат, пятно) на одну сторону детали.
function Textures.decal(part, name, face)
	local image = Textures.get(name)
	if not image then
		return false
	end
	local decal = Instance.new("Decal")
	decal.Texture = image
	decal.Face = face
	decal.Parent = part
	return true
end

return Textures
