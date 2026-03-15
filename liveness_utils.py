import cv2
import numpy as np
import mediapipe as mp

# As constantes do MediaPipe devem ser definidas ou passadas, mas 
# para a função ser independente, usaremos a que passamos por argumento.

# Parâmetros de calibração (ajuste conforme o teste)
# Estas são as proporções mínimas e máximas de profundidade/largura
# esperadas de um rosto real em uma câmera RGB.
MIN_LIVENESS_RATIO = 0.15 
MAX_LIVENESS_RATIO = 0.85 
MIN_FACE_AREA_PX = 1000  # Área mínima para considerar (evita falsos positivos em rostos muito pequenos)

def verificar_liveness_face_mesh(frame, face_mesh):
    """
    Verifica a presença de um rosto e estima a sua profundidade (liveness) 
    usando a malha 3D do MediaPipe Face Mesh.

    frame: Imagem (array numpy) no formato BGR do OpenCV.
    face_mesh: Instância do mp.solutions.face_mesh.FaceMesh.

    Retorna: Dicionário com 'sucesso', 'liveness_passou', 'mensagem', 'dimensoes'.
    """
    
    # 1. Preparação da Imagem (MP espera RGB)
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    frame_height, frame_width, _ = frame.shape
    
    # 2. Processamento com MediaPipe
    results = face_mesh.process(rgb_frame)
    
    if not results.multi_face_landmarks:
        return {
            "sucesso": False, 
            "liveness_passou": False,
            "mensagem": "❌ Nenhum rosto detectado na imagem."
        }
    
    # Processa apenas o primeiro (ou maior) rosto, se houver
    landmarks = results.multi_face_landmarks[0].landmark
    
    # 3. Mapeamento para Coordenadas 3D (X, Y, Z)
    # Z é a profundidade (profundidade relativa ao centro do rosto na imagem)
    
    landmarks_coords = np.array([
        (lm.x * frame_width, lm.y * frame_height, lm.z * frame_width) 
        for lm in landmarks
    ])
    
    # 4. Cálculo de Dimensões para Análise e Retorno
    x_coords = landmarks_coords[:, 0]
    y_coords = landmarks_coords[:, 1]
    z_coords = landmarks_coords[:, 2]
    
    min_x, max_x = np.min(x_coords), np.max(x_coords)
    min_y, max_y = np.min(y_coords), np.max(y_coords)
    min_z, max_z = np.min(z_coords), np.max(z_coords)
    
    face_width = max_x - min_x
    face_height = max_y - min_y
    face_depth = max_z - min_z # Profundidade/extensão do rosto na dimensão Z
    face_area = face_width * face_height
    
    # Dimensões para o retângulo de feedback
    dimensoes_retorno = {
        "top": int(min_y), 
        "right": int(max_x), 
        "bottom": int(max_y), 
        "left": int(min_x)
    }
    
    # 5. Lógica de Liveness Baseada em Profundidade
    
    # 5.1. Checagem de área mínima
    if face_area < MIN_FACE_AREA_PX:
        return {
            "sucesso": True, # Rosto detectado com sucesso (mas com alerta)
            "liveness_passou": False, 
            "mensagem": "⚠️ Rosto muito pequeno. Aproxime-se mais da câmera.",
            "dimensoes": dimensoes_retorno
        }

    # 5.2. Cálculo da Proporção Profundidade / Largura (Liveness Ratio)
    # Um rosto impresso/plano terá face_depth muito próxima de zero ou muito baixa.
    # Usamos face_width como base para normalizar, pois é menos afetada por movimentos
    # de cabeça do que face_height.
    if face_width < 1: 
        # Evita divisão por zero
        ratio = 0 
    else:
        ratio = face_depth / face_width

    
    # 5.3. Validação do Liveness
    if ratio < MIN_LIVENESS_RATIO:
        # Se a profundidade for muito baixa em relação à largura (parece plano)
        mensagem = f"❌ ALERTA! Profundidade insuficiente (Ratio: {ratio:.2f}). **Pode ser um spoofing.**"
        liveness_passou = False
    elif ratio > MAX_LIVENESS_RATIO:
        # Se a profundidade for muito alta (algo muito próximo da câmera ou artefato)
        mensagem = f"⚠️ ALERTA! Profundidade exagerada (Ratio: {ratio:.2f}). Não parece um rosto natural."
        liveness_passou = False
    else:
        # Passou no teste de profundidade
        mensagem = f"✅ Liveness OK (Ratio: {ratio:.2f})."
        liveness_passou = True
        
    
    return {
        "sucesso": True, 
        "liveness_passou": liveness_passou,
        "mensagem": mensagem,
        "dimensoes": dimensoes_retorno
    }