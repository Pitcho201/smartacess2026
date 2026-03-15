import os
import sqlite3
import face_recognition
import pickle
import csv
import cv2
import numpy as np
from landmark_utils import extrair_landmarks_da_imagem, extrair_vetor_estrutural, calcular_distancia_estrutural

# 1. NOVO CAMINHO PÚBLICO: Onde as fotos estão acessíveis pelo navegador
FOTOS_PATH = "/known_faces/" 

# ----------------------------------------------------------------------
# FUNÇÕES DE BUSCA DE DADOS (AGORA INJETAM URL_IMAGEM)
# ----------------------------------------------------------------------

def _adicionar_url_imagem(dados, numero_bi):
    """ Constrói e adiciona a chave 'url_imagem' ao dicionário de dados. """
    if not dados:
        return dados
        
    # Tenta construir a URL com as extensões mais comuns
    for ext in ['.jpg', '.jpeg', '.png']:
        url = f"{FOTOS_PATH}{numero_bi}{ext}"
        dados['url_imagem'] = url
        return dados
    
    return dados


def buscar_dados_estudante(numero_bi):
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    # Seleciona os campos necessários para o infoCard, AGORA INCLUINDO 'numero_estudante'
    estudante = conn.execute("SELECT id, nome, numero_bi, curso, ano_frequencia, periodo, numero_estudante FROM estudantes WHERE numero_bi = ?", (numero_bi,)).fetchone()
    conn.close()
    
    dados = dict(estudante) if estudante else {}
    
    # A função _adicionar_url_imagem está OK para criar a chave 'url_imagem'
    return _adicionar_url_imagem(dados, numero_bi)


def buscar_dados_funcionario(numero_bi):
    """ Busca dados de funcionário e injeta a URL da imagem. """
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    # Seleciona os campos necessários para o infoCard do funcionário
    funcionario = conn.execute("SELECT id, nome, numero_bi, funcao, departamento FROM funcionarios WHERE numero_bi = ?", (numero_bi,)).fetchone()
    conn.close()
    
    dados = dict(funcionario) if funcionario else {}
    
    # CORREÇÃO: INJEÇÃO DA URL DA IMAGEM
    return _adicionar_url_imagem(dados, numero_bi)

# ----------------------------------------------------------------------
# FUNÇÃO DE CARREGAMENTO DO CACHE (AGORA BUSCA DADOS COMPLETOS)
# ----------------------------------------------------------------------

def carregar_rostos_conhecidos_incremental(existing_names=None):
    encodings_novos = []
    nomes_novos = []
    dados_novos = {}
    vetores_estruturais_novos = {}

    if existing_names is None:
        existing_names = set()

    print("🔄 Verificando novos rostos...")

    for filename in os.listdir('known_faces'):
        if filename.endswith(('.jpg', '.jpeg', '.png')):
            numero_bi = os.path.splitext(filename)[0]
            if numero_bi in existing_names:
                continue

            path = os.path.join('known_faces', filename)
            
            # --- Tenta carregar a imagem e encodings ---
            try:
                imagem = face_recognition.load_image_file(path)
                encoding = face_recognition.face_encodings(imagem)
                
                # Busca dados de Estudante OU Funcionário (inclui url_imagem)
                dados_usuario = buscar_dados_estudante(numero_bi)
                if not dados_usuario:
                    dados_usuario = buscar_dados_funcionario(numero_bi)
                
            except Exception as e:
                # Se falhar ao carregar a imagem (arquivo corrompido, etc.)
                print(f"⚠️ Erro ao processar arquivo {filename}: {e}")
                continue
            
            # --- Se o rosto for detectado e tiver dados ---
            if encoding and dados_usuario:
                encodings_novos.append(encoding[0])
                nomes_novos.append(numero_bi)
                
                # CORREÇÃO: Adiciona os dados que agora contêm 'url_imagem'
                dados_novos[numero_bi] = dados_usuario 
                
                _, landmarks = extrair_landmarks_da_imagem(imagem)
                vetor_estrutural = extrair_vetor_estrutural(landmarks)
                vetores_estruturais_novos[numero_bi] = vetor_estrutural
                
                print(f"✅ Novo rosto carregado: {numero_bi}")
            elif encoding:
                 # Rosto detectado, mas não encontrado no BD
                 print(f"⚠️ Rosto de BI {numero_bi} detectado, mas não encontrado no cadastro.")
            else:
                print(f"⚠️ Nenhum rosto detectado em {filename}")

    print(f"✔️ Total de novos rostos: {len(encodings_novos)}")
    return encodings_novos, nomes_novos, dados_novos, vetores_estruturais_novos

# facial_utils.py (Adicione esta função)
# ...
def carregar_rostos_conhecidos_incremental_unico(numero_bi):
    encodings_novos = []
    nomes_novos = []
    dados_novos = {}
    vetores_estruturais_novos = {}

    path = None
    # Verifica a existência do arquivo com as extensões mais comuns
    for ext in ['.jpg', '.jpeg', '.png']:
        temp_path = os.path.join('known_faces', f"{numero_bi}{ext}")
        if os.path.exists(temp_path):
            path = temp_path
            break
            
    if not path:
        return None, None, None, None, f"❌ Arquivo de foto para BI {numero_bi} não encontrado em 'known_faces'."

    # --- Tenta carregar a imagem e encodings ---
    try:
        imagem = face_recognition.load_image_file(path)
        encoding = face_recognition.face_encodings(imagem)
        
        dados_usuario = buscar_dados_estudante(numero_bi)
        if not dados_usuario:
            dados_usuario = buscar_dados_funcionario(numero_bi)
        
    except Exception as e:
        return None, None, None, None, f"⚠️ Erro ao processar arquivo {numero_bi}: {e}"

    # --- Se o rosto for detectado e tiver dados ---
    if encoding and dados_usuario:
        encodings_novos.append(encoding[0])
        nomes_novos.append(numero_bi)
        dados_novos[numero_bi] = dados_usuario 
        
        _, landmarks = extrair_landmarks_da_imagem(imagem)
        vetor_estrutural = extrair_vetor_estrutural(landmarks)
        vetores_estruturais_novos[numero_bi] = vetor_estrutural
        
        return encodings_novos, nomes_novos, dados_novos, vetores_estruturais_novos, f"✅ Rosto de {numero_bi} recarregado com sucesso."
    
    elif encoding:
        return None, None, None, None, f"⚠️ Rosto de BI {numero_bi} detectado, mas não encontrado no cadastro do BD."
    
    else:
        return None, None, None, None, f"❌ Nenhum rosto detectado na foto de {numero_bi}."

# ----------------------------------------------------------------------
# FUNÇÃO DE IDENTIFICAÇÃO (INALTERADA - USA O CACHE CORRIGIDO)
# ----------------------------------------------------------------------

def identificar_rosto(frame, encodings_base, nomes_base, dados_base, vetores_estruturais_base, tolerance=0.4):
    import cv2
    import numpy as np

    small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
    rgb_small = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
    face_locations = face_recognition.face_locations(rgb_small)
    encodings = face_recognition.face_encodings(rgb_small, face_locations)

    if not encodings or not face_locations:
        return {"sucesso": False, "mensagem": "❌ Nenhum rosto detectado."}

    face_areas = [(b - t) * (r - l) for t, r, b, l in face_locations]
    largest_index = int(np.argmax(face_areas))
    face_encoding = encodings[largest_index]
    top, right, bottom, left = face_locations[largest_index]

    landmarks = face_recognition.face_landmarks(rgb_small, [face_locations[largest_index]])
    vetor_estrutural = extrair_vetor_estrutural(landmarks[0]) if landmarks else None

    matches = face_recognition.compare_faces(encodings_base, face_encoding, tolerance=tolerance)
    face_distances = face_recognition.face_distance(encodings_base, face_encoding)

    melhor_indice = None
    menor_distancia = float('inf')

    for i, match in enumerate(matches):
        if match:
            estrutura_ref = vetores_estruturais_base.get(nomes_base[i])
            distancia_geo = calcular_distancia_estrutural(vetor_estrutural, estrutura_ref)
            if distancia_geo < menor_distancia:
                menor_distancia = distancia_geo
                melhor_indice = i

    if melhor_indice is not None:
        numero_bi = nomes_base[melhor_indice]
        # DADOS VÊM DIRETAMENTE DO CACHE (E AGORA CONTÊM 'url_imagem' GRAÇAS À CORREÇÃO)
        dados_usuario = dados_base.get(numero_bi, {}) 
        return {
            "sucesso": True,
            "numero_bi": numero_bi,
            "dados": dados_usuario, 
            "coordenadas": (top * 4, right * 4, bottom * 4, left * 4),
            "dimensoes": frame.shape[:2]
        }

    return {"sucesso": False, "mensagem": "❌ Rosto não reconhecido."}

# ----------------------------------------------------------------------
# FUNÇÕES DE CACHE (INALTERADAS)
# ----------------------------------------------------------------------

def salvar_cache(encodings, nomes, dados, estruturas, caminho='face_cache.pkl'):
    with open(caminho, 'wb') as f:
        pickle.dump((encodings, nomes, dados, estruturas), f)

def carregar_cache(caminho='face_cache.pkl'):
    if os.path.exists(caminho):
        with open(caminho, 'rb') as f:
            return pickle.load(f)
    return None, None, None, None

# ----------------------------------------------------------------------
# FUNÇÃO DE MÚLTIPLOS ROSTOS (INALTERADA)

# ----------------------------------------------------------------------

def identificar_multiplos_rostos(frame, known_face_encodings, known_face_names, known_face_data, known_face_estruturas):
    """
    Identifica todos os rostos em um frame (imagem de grupo) e retorna todos os resultados.
    
    Retorna: Uma lista de dicionários, cada um contendo 'sucesso', 'numero_bi', 'dados', e 'coordenadas'
    """
    # Redimensiona o frame para processamento mais rápido (opcional, mas recomendado)
    small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
    rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

    # Encontra todos os rostos e seus encodings no frame atual
    face_locations = face_recognition.face_locations(rgb_small_frame)
    face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

    resultados_finais = []
    scale = 4 # Fator de redimensionamento (0.25 -> 4)

    for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
        # Compara o rosto do frame com os rostos conhecidos
        matches = face_recognition.compare_faces(known_face_encodings, face_encoding, tolerance=0.5)
        name = "Desconhecido"
        
        # Tenta encontrar o rosto mais próximo
        face_distances = face_recognition.face_distance(known_face_encodings, face_encoding)
        best_match_index = np.argmin(face_distances)
        
        resultado = {"sucesso": False, "mensagem": "Rosto não identificado."}

        if matches[best_match_index] and face_distances[best_match_index] < 0.5:
            name = known_face_names[best_match_index]
            
            # Recalcula as coordenadas para o tamanho original
            top *= scale
            right *= scale
            bottom *= scale
            left *= scale
            
            resultado = {
                "sucesso": True,
                "numero_bi": name,
                "dados": known_face_data.get(name, {}), # DADOS AGORA TÊM 'url_imagem'
                "coordenadas": [top, right, bottom, left],
                "dimensoes": [frame.shape[0], frame.shape[1]] # Altura, Largura
            }
        
        if resultado["sucesso"]:
             # Só adiciona resultados que tiveram sucesso no reconhecimento
             resultados_finais.append(resultado)

    # Se nenhum rosto foi adicionado, retorne um array com um resultado de falha
    if not resultados_finais:
        return [{"sucesso": False, "mensagem": "Nenhum rosto conhecido foi detectado."}]
    
    return resultados_finais

