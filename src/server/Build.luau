-- Мелкие помощники для постройки карт из деталей.
local Build = {}

-- Создаёт закреплённую деталь с заданными свойствами и (необязательно) тегом.
function Build.part(className, parent, props, tag)
	local part = Instance.new(className)
	part.Anchored = true
	part.TopSurface = Enum.SurfaceType.Smooth
	part.BottomSurface = Enum.SurfaceType.Smooth
	-- Shape влияет на допустимый Size, поэтому задаём её первой.
	if props.Shape then
		part.Shape = props.Shape
	end
	for key, value in props do
		part[key] = value
	end
	if tag then
		part:AddTag(tag)
	end
	part.Parent = parent
	return part
end

-- Цилиндр от точки from до точки to (у цилиндра в Roblox ось — X).
function Build.cylinder(parent, from, to, diameter, props)
	local offset = to - from
	local center = (from + to) / 2
	props.Shape = Enum.PartType.Cylinder
	props.Size = Vector3.new(offset.Magnitude, diameter, diameter)
	if math.abs(offset.Unit.Y) > 0.999 then
		-- вертикальный: lookAt вдоль оси Y не определён, просто поворачиваем X вверх
		props.CFrame = CFrame.new(center) * CFrame.Angles(0, 0, math.pi / 2)
	else
		props.CFrame = CFrame.lookAt(center, to) * CFrame.Angles(0, math.pi / 2, 0)
	end
	return Build.part("Part", parent, props)
end

function Build.light(part, className, props)
	local light = Instance.new(className)
	for key, value in props do
		light[key] = value
	end
	light.Parent = part
	return light
end

-- Надписи на стороне детали. lines: { { text, height (доля), color, rotation?, font? } }
function Build.surfaceText(part, face, lines, lightInfluence)
	local gui = Instance.new("SurfaceGui")
	gui.Face = face
	gui.SizingMode = Enum.SurfaceGuiSizingMode.PixelsPerStud
	gui.PixelsPerStud = 30
	gui.LightInfluence = lightInfluence
	local layout = Instance.new("UIListLayout")
	layout.HorizontalAlignment = Enum.HorizontalAlignment.Center
	layout.VerticalAlignment = Enum.VerticalAlignment.Center
	layout.Parent = gui
	local labels = {}
	for _, line in lines do
		local label = Instance.new("TextLabel")
		label.Size = UDim2.fromScale(0.9, line.height)
		label.BackgroundTransparency = 1
		label.Font = line.font or Enum.Font.GothamBlack
		label.TextScaled = true
		label.TextColor3 = line.color
		label.Text = line.text
		label.Rotation = line.rotation or 0
		label.Parent = gui
		table.insert(labels, label)
	end
	gui.Parent = part
	return gui, labels
end

function Build.shuffle(list, rng)
	for i = #list, 2, -1 do
		local j = rng:NextInteger(1, i)
		list[i], list[j] = list[j], list[i]
	end
	return list
end

return Build
