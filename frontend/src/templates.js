// =====================================================
// GENERIC TEMPLATE LOOKUP
// =====================================================

export function getTemplate(

  definitions,

  category,

  templateId
){

  return (

    definitions
    ?. [category]
    ?. [templateId]

    || null
  );
}


// =====================================================
// PROP TEMPLATE
// =====================================================

export function getPropTemplate(

  definitions,

  prop
){

  return getTemplate(

    definitions,

    "prop_templates",

    prop?.template
  );
}


// =====================================================
// CHARACTER TEMPLATE
// =====================================================

export function getCharacterTemplate(

  definitions,

  character
){

  return getTemplate(

    definitions,

    "character_templates",

    character?.template
  );
}


// =====================================================
// ITEM TEMPLATE
// =====================================================

export function getItemTemplate(

  definitions,

  item
){

  return getTemplate(

    definitions,

    "item_templates",

    item?.template
  );
}


// =====================================================
// RESOLVE INSTANCE
// =====================================================

export function resolveInstance(

  definitions,

  category,

  instance
){

  const template =
    getTemplate(

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
// RESOLVED PROP
// =====================================================

export function resolveProp(

  definitions,

  prop
){

  return resolveInstance(

    definitions,

    "prop_templates",

    prop
  );
}


// =====================================================
// RESOLVED CHARACTER
// =====================================================

export function resolveCharacter(

  definitions,

  character
){

  return resolveInstance(

    definitions,

    "character_templates",

    character
  );
}


// =====================================================
// FLOORPLAN TEMPLATE
// =====================================================

export function getFloorplanTemplate(

  definitions,

  building
){

  return getTemplate(

    definitions,

    "floorplan_templates",

    building?.template
  );
}


// =====================================================
// RESOLVED FLOORPLAN
// =====================================================

export function resolveFloorplan(

  definitions,

  building
){

  return resolveInstance(

    definitions,

    "floorplan_templates",

    building
  );
}


export function getMaterialTemplate(

  definitions,

  materialId
){

  return getTemplate(

    definitions,

    "material_templates",

    materialId
  );
}