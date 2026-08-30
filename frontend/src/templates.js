// =====================================================
// GENERIC TEMPLATE LOOKUP
// =====================================================

export function getTemplate(definitions, category, templateId){

  if(!definitions || !category || !templateId){
    return null;
  }

  return definitions?.[category]?.[templateId] || null;
}


// =====================================================
// RESOLVE INSTANCE
// =====================================================

export function resolveInstance(definitions, category, instance){

  const template = getTemplate(
    definitions,
    category,
    instance?.template
  );

  if(!template){
    return instance;
  }

  return {
    ...template,
    ...instance
  };
}


// =====================================================
// BASIC TEMPLATE GETTERS
// =====================================================

export function getPropTemplate(definitions, prop){
  return getTemplate(definitions, "prop_templates", prop?.template);
}

export function getCharacterTemplate(definitions, character){
  return getTemplate(definitions, "character_templates", character?.template);
}

export function getItemTemplate(definitions, item){
  // Item instances carry "template_id", not "template" -- unlike props/
  // characters/buildings (see backend/systems/personal_items.py::make_item()).
  // Was previously unused anywhere in the frontend, so this mismatch never
  // surfaced.
  return getTemplate(definitions, "item_templates", item?.template_id);
}

export function getFloorplanTemplate(definitions, building){
  return getTemplate(definitions, "floorplan_templates", building?.template);
}

export function getMaterialTemplate(definitions, materialId){
  return getTemplate(definitions, "material_templates", materialId);
}


// =====================================================
// NEW TEMPLATE GETTERS
// =====================================================

export function getRecipeTemplate(definitions, recipeId){
  return getTemplate(definitions, "recipe_templates", recipeId);
}

export function getProductTemplate(definitions, productId){
  return getTemplate(definitions, "product_templates", productId);
}

export function getApplianceTemplate(definitions, applianceId){
  return getTemplate(definitions, "appliance_templates", applianceId);
}

export function getVehicleTemplate(definitions, vehicleId){
  return getTemplate(definitions, "vehicle_templates", vehicleId);
}

export function getServiceTemplate(definitions, serviceId){
  return getTemplate(definitions, "service_templates", serviceId);
}

export function getStorageTemplate(definitions, storageId){
  return getTemplate(definitions, "storage_templates", storageId);
}

export function getSocialTemplate(definitions, socialId){
  return getTemplate(definitions, "social_templates", socialId);
}

export function getNeedTemplate(definitions, needId){
  return getTemplate(definitions, "need_templates", needId);
}


// =====================================================
// RESOLVERS
// =====================================================

export function resolveProp(definitions, prop){
  return resolveInstance(definitions, "prop_templates", prop);
}

export function resolveCharacter(definitions, character){
  return resolveInstance(definitions, "character_templates", character);
}

export function resolveItem(definitions, item){
  // Can't delegate to resolveInstance() -- it reads instance.template,
  // but item instances carry template_id (see getItemTemplate() above).
  const template = getItemTemplate(definitions, item);
  if(!template){
    return item;
  }
  return { ...template, ...item };
}

export function resolveFloorplan(definitions, building){
  return resolveInstance(definitions, "floorplan_templates", building);
}

export function resolveRecipe(definitions, recipe){
  return resolveInstance(definitions, "recipe_templates", recipe);
}

export function resolveProduct(definitions, product){
  return resolveInstance(definitions, "product_templates", product);
}

export function resolveAppliance(definitions, appliance){
  return resolveInstance(definitions, "appliance_templates", appliance);
}

export function resolveVehicle(definitions, vehicle){
  return resolveInstance(definitions, "vehicle_templates", vehicle);
}

export function resolveService(definitions, service){
  return resolveInstance(definitions, "service_templates", service);
}

export function resolveStorage(definitions, storage){
  return resolveInstance(definitions, "storage_templates", storage);
}