RECIPES = {

    "simple_pasta": {

        "difficulty": 0.3,

        "time_minutes": 25,

        "nutrition": 0.7,

        "stages": [

            {

                "name": "boil_water",

                "duration": 5,

                "active": False
            },

            {

                "name": "cook_carbs",

                "inputs": {

                    "FOOD_CARB": 1
                },

                "duration": 12,

                "active": False
            },

            {

                "name": "prepare_sauce",

                "inputs": {

                    "FOOD_VEGETABLE": 1,

                    "FOOD_SPICE": 1
                },

                "duration": 8,

                "active": True
            }
        ],

        "output": {

            "resource_type": "MEAL",

            "servings": 3
        }
    },

    "protein_plate": {

        "difficulty": 0.5,

        "time_minutes": 40,

        "nutrition": 0.9,

        "stages": [

            {

                "name": "roast_protein",

                "inputs": {

                    "FOOD_PROTEIN": 1
                },

                "duration": 30,

                "active": False
            },

            {

                "name": "cook_vegetables",

                "inputs": {

                    "FOOD_VEGETABLE": 1
                },

                "duration": 12,

                "active": True
            },

            {

                "name": "prepare_carbs",

                "inputs": {

                    "FOOD_CARB": 1
                },

                "duration": 15,

                "active": False
            }
        ],

        "output": {

            "resource_type": "MEAL",

            "servings": 4
        }
    }
}