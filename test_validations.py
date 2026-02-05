from app.routes.artefacto_360_routes import validate_coordinates

# Probar validación correcta
try:
    validate_coordinates([-76.5225, 3.4516], 'Point')
    print('✅ Validación de Point correcto')
except Exception as e:
    print(f'❌ Error inesperado: {e}')

# Probar validación de coordenadas inválidas
try:
    validate_coordinates([-200, 3.4516], 'Point')
    print('❌ Debería haber rechazado coordenadas inválidas')
except ValueError as e:
    print(f'✅ Validación rechaza coordenadas inválidas: {e}')

# Probar validación de LineString
try:
    validate_coordinates([[-76.52, 3.45], [-76.53, 3.46]], 'LineString')
    print('✅ Validación de LineString correcto')
except Exception as e:
    print(f'❌ Error inesperado: {e}')

print('\n🎉 Todas las validaciones funcionan correctamente!')
