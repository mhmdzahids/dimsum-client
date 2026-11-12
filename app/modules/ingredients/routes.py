from fastapi import APIRouter, Request, Depends
from app.shared.response import json_response
from app.core.db import db_session
from app.modules.ingredients.service import IngredientService
from app.core.security import admin_required, staff_or_admin_required
ingredients_bp = APIRouter(dependencies=[Depends(staff_or_admin_required)])

@ingredients_bp.api_route('', methods=['GET'])
def get_ingredients(request: Request):
    ingredients = IngredientService.get_all_ingredients(db_session)
    return json_response([i.to_dict() for i in ingredients])

@ingredients_bp.api_route('/{ingredient_id}', methods=['GET'])
def get_ingredient(request: Request, ingredient_id):
    ingredient = IngredientService.get_ingredient_by_id(db_session, ingredient_id)
    if not ingredient:
        return json_response({'error': 'Not found'}, 404)
    return json_response(ingredient.to_dict())

@ingredients_bp.api_route('', methods=['POST'], dependencies=[Depends(admin_required)])
def create_ingredient(request: Request):
    data = request.state.payload
    ingredient = IngredientService.create_ingredient(db_session, name=data['name'], unit=data['unit'], current_stock=data.get('current_stock', 0.0), min_buffer_stock=data.get('min_buffer_stock', 10.0))
    return json_response(ingredient.to_dict(), 201)

@ingredients_bp.api_route('/{ingredient_id}', methods=['PUT'], dependencies=[Depends(admin_required)])
def update_ingredient(request: Request, ingredient_id):
    data = request.state.payload
    ingredient = IngredientService.update_ingredient(db_session, ingredient_id, **data)
    if not ingredient:
        return json_response({'error': 'Not found'}, 404)
    return json_response(ingredient.to_dict())

@ingredients_bp.api_route('/{ingredient_id}', methods=['DELETE'], dependencies=[Depends(admin_required)])
def delete_ingredient(request: Request, ingredient_id):
    if IngredientService.delete_ingredient(db_session, ingredient_id):
        return json_response({'message': 'Deleted'})
    return json_response({'error': 'Not found'}, 404)

@ingredients_bp.api_route('/product/{product_id}/recipe', methods=['GET'])
def get_product_recipe(request: Request, product_id):
    recipe = IngredientService.get_product_recipe(db_session, product_id)
    return json_response([r.to_dict() for r in recipe])

@ingredients_bp.api_route('/product/{product_id}/recipe', methods=['POST'], dependencies=[Depends(admin_required)])
def add_to_recipe(request: Request, product_id):
    data = request.state.payload
    recipe = IngredientService.add_ingredient_to_product(db_session, product_id, data['ingredient_id'], float(data.get('amount_per_pack', 0.0)), data.get('unit_measure', 'pcs'), data.get('notes'))
    return json_response(recipe.to_dict(), 201)

@ingredients_bp.api_route('/product/{product_id}/recipe/{ingredient_id}', methods=['DELETE'], dependencies=[Depends(admin_required)])
def remove_from_recipe(request: Request, product_id, ingredient_id):
    if IngredientService.remove_ingredient_from_product(db_session, product_id, ingredient_id):
        return json_response({'message': 'Deleted'})
    return json_response({'error': 'Not found'}, 404)

@ingredients_bp.api_route('/product/{product_id}/calculate', methods=['POST'])
def calculate_for_product(request: Request, product_id):
    """Calculate ingredients needed for X quantity of a product"""
    data = request.state.payload
    quantity = int(data.get('quantity', 1))
    result = IngredientService.calculate_ingredients_needed(db_session, product_id, quantity)
    return json_response({'product_id': product_id, 'quantity': quantity, 'ingredients': result})

@ingredients_bp.api_route('/calculate-multiple', methods=['POST'])
def calculate_for_multiple(request: Request):
    """Calculate aggregated ingredients for multiple products"""
    data = request.state.payload
    product_targets = data.get('product_targets', [])
    result = IngredientService.calculate_ingredients_for_multiple_products(db_session, product_targets)
    return json_response({'product_targets': product_targets, 'ingredients': result})

@ingredients_bp.api_route('/check-insufficient', methods=['POST'])
def check_insufficient(request: Request):
    """Check which ingredients are insufficient (bahan kurang)"""
    data = request.state.payload
    product_targets = data.get('product_targets', [])
    insufficient = IngredientService.check_insufficient_ingredients(db_session, product_targets)
    return json_response({'product_targets': product_targets, 'insufficient_count': len(insufficient), 'insufficient_ingredients': insufficient})

@ingredients_bp.api_route('/{ingredient_id}/stock', methods=['PUT'], dependencies=[Depends(admin_required)])
def update_stock(request: Request, ingredient_id):
    """Update ingredient stock (set/add/subtract)"""
    data = request.state.payload
    operation = data.get('operation', 'set')
    quantity = float(data.get('quantity', 0))
    ingredient = IngredientService.update_ingredient_stock(db_session, ingredient_id, quantity, operation)
    if not ingredient:
        return json_response({'error': 'Not found'}, 404)
    return json_response({'message': f'Stock updated ({operation})', 'ingredient': ingredient.to_dict()})
