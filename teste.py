import sqlite3
from app import registrar_entrada

def buscar_nome_estudante(bi):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT nome FROM estudantes WHERE numero_bi = ?", (bi,))
    resultado = cursor.fetchone()
    conn.close()
    return resultado[0] if resultado else None

def verificar_entrada_existente_hoje(bi):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT e.data_hora 
        FROM entradas e
        INNER JOIN estudantes s ON e.estudante_id = s.id
        WHERE s.numero_bi = ? AND date(e.data_hora) = date('now')
    """, (bi,))
    resultado = cursor.fetchone()
    conn.close()
    return resultado is not None

def test_registrar_entrada_existente():
    bi_teste = "922841540RM123"  # Certifique-se que este BI existe na tabela estudantes
    nome = buscar_nome_estudante(bi_teste)

    if not nome:
        print(f"❌ Estudante com BI {bi_teste} não encontrado na base de dados.")
        return

    print(f"🔍 Verificando entrada para: {nome} ({bi_teste})...")

    entrada_ja_registrada = verificar_entrada_existente_hoje(bi_teste)
    resultado_registro = registrar_entrada(bi_teste)

    if entrada_ja_registrada:
        print(f"ℹ️ {nome} já foi registrado hoje.")
    else:
        if verificar_entrada_existente_hoje(bi_teste):
            print(f"✅ Nova entrada registrada hoje para {nome}.")
        else:
            print(f"❌ Erro: Não foi possível registrar a entrada de {nome}.")
            assert False, "Entrada não registrada"

# 🔁 Executa o teste manualmente
if __name__ == "__main__":
    print("Iniciando teste de registro de entrada...")
    test_registrar_entrada_existente()
    print("Teste concluído.")
