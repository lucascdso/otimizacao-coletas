import streamlit as st
import pandas as pd
from datetime import timedelta
import io

# ==============================================================================
# 1. CONFIGURAÇÕES DA PÁGINA E VARIÁVEIS GERAIS
# ==============================================================================
st.set_page_config(page_title="Dashboard de SLA e Coletas", layout="wide")
st.title("🚚 Análise de SLA de Coletas e Mix de Atrasos")
st.write("Faça o upload do seu relatório de rastreamento para gerar os indicadores de Nível de Serviço.")

# Horário limite (Saída da doca/Bipe final) - SEU CÓDIGO ORIGINAL
horarios_saida = {
    'LOGPLACE': '20:00:00',
    'AZUL NINJA': '15:00:00',
    'TOTAL EXPRESS - EXPRESSO': '15:00:00',
    'CORREIOS PAC': '20:00:00',
    'CORREIOS SEDEX': '20:00:00',
    'FAVORITA': '20:00:00',
    'TOTAL EXPRESS - STANDARD': '15:00:00',
    'JADLOG': '20:00:00',
    'JADLOG - LEVES': '20:00:00',
    'JADLOG PESADOS': '20:00:00',
    'MAGALOG (IN)': '20:30:00',
    'AZUL': '20:00:00',
    'AZUL CARGO': '20:00:00',
    'MOVVI': '15:00:00'
}

# Horário de Corte (Disponibilização da carga) - DADOS DO SEU PRINT
horarios_corte_disp = {
    'LOGPLACE': '19:00:00',
    'AZUL NINJA': '14:00:00',
    'TOTAL EXPRESS - EXPRESSO': '14:00:00',
    'CORREIOS PAC': '19:00:00',
    'CORREIOS SEDEX': '19:00:00',
    'FAVORITA': '19:00:00',
    'TOTAL EXPRESS - STANDARD': '14:00:00',
    'JADLOG': '19:00:00',
    'JADLOG - LEVES': '19:00:00', 
    'JADLOG PESADOS': '19:00:00',
    'MAGALOG (IN)': '19:00:00',
    'AZUL': '19:00:00',
    'AZUL CARGO': '19:00:00', 
    'MOVVI': '14:00:00'
}

# ==============================================================================
# 2. FUNÇÃO DO MOTOR DE SLA (Dupla Validação)
# ==============================================================================
def classificar_sla(row):
    transp = str(row.get('Transportadora', '')).strip().upper()
    dt_disp = row.get('Dt/Hr Disp Coleta')
    dt_coleta = row.get('Dt/Hr Coleta')
    
    if pd.isna(dt_disp) or pd.isna(dt_coleta): 
        return pd.Series([pd.NaT, 'Sem Dados'])
        
    # Busca os horários mapeados para a transportadora (ordena por tamanho para nomes compostos)
    horario_saida_str = next((v for k, v in sorted(horarios_saida.items(), key=lambda x: len(x[0]), reverse=True) if k in transp), None)
    horario_corte_str = next((v for k, v in sorted(horarios_corte_disp.items(), key=lambda x: len(x[0]), reverse=True) if k in transp), None)

    if not horario_saida_str or not horario_corte_str: 
        return pd.Series([pd.NaT, 'Transportador Não Mapeado'])
        
    hora_corte_disp = pd.to_datetime(horario_corte_str, format='%H:%M:%S').time()
    
    # 1. Define a data inicial do prazo como a data de disponibilização
    data_prazo = dt_disp.date()
    
    # 2. Lógica de janela: Se for fim de semana ou passou do horário de corte do print, pula pro dia seguinte
    if dt_disp.weekday() >= 5 or dt_disp.time() > hora_corte_disp:
        data_prazo += timedelta(days=1)
        
    # 3. Garante que o prazo final caia em um dia útil (pula sábado e domingo)
    # 0=Seg, 1=Ter, 2=Qua, 3=Qui, 4=Sex, 5=Sáb, 6=Dom
    while data_prazo.weekday() > 4: 
        data_prazo += timedelta(days=1)
        
    # 4. Junta a data calculada com o horário de SAÍDA (bipe) original
    prazo_limite = pd.to_datetime(f"{data_prazo} {horario_saida_str}")
    
    # 5. Compara
    status = 'No Prazo' if dt_coleta <= prazo_limite else 'Atrasado'
    
    return pd.Series([prazo_limite, status])

# Helpers para os cálculos
def calc_perc_atraso_tipo(group, tipo_alvo):
    atrasados = group[group['Status_SLA'] == 'Atrasado']
    if atrasados.empty: return 0.0
    total_atrasados = len(atrasados)
    if 'Tipo Produto' not in atrasados.columns: return 0.0
    tipo_count = atrasados['Tipo Produto'].astype(str).str.upper().str.contains(tipo_alvo.upper()).sum()
    return (tipo_count / total_atrasados) * 100

@st.cache_data
def convert_df_to_csv(df):
    return df.to_csv(index=False, sep=';', decimal=',').encode('utf-8')

# ==============================================================================
# 3. INTERFACE E PROCESSAMENTO
# ==============================================================================
uploaded_file = st.file_uploader("Selecione o arquivo CSV de Rastreamento", type=["csv"])

if uploaded_file is not None:
    with st.spinner("Lendo e processando os dados de SLA... Por favor, aguarde."):
        # Carregamento
        df = pd.read_csv(uploaded_file, low_memory=False, sep=';')
        qtd_original = len(df)

        # Limpeza
        if 'Pedido' in df.columns:
            df = df[~df['Pedido'].astype(str).str.match(r'^10\d{8}$')]
            
        if 'CD' in df.columns:
            df = df.dropna(subset=['CD'])
            df = df[df['CD'].astype(str).str.strip() != '']
            
        if 'Status Tracking' in df.columns:
            df = df[~df['Status Tracking'].astype(str).str.upper().str.contains('CANCELADO')]

        if 'Peso' in df.columns:
            df['Peso'] = df['Peso'].astype(str).str.replace(',', '.').astype(float).fillna(0) / 1000.0
        else:
            df['Peso'] = 0

        qtd_pos_limpeza = len(df)
        
        # Conversão de Datas e Execução do Motor SLA
        if 'Dt/Hr Disp Coleta' in df.columns and 'Dt/Hr Coleta' in df.columns:
            df['Dt/Hr Disp Coleta'] = pd.to_datetime(df['Dt/Hr Disp Coleta'], dayfirst=True, errors='coerce')
            df['Dt/Hr Coleta'] = pd.to_datetime(df['Dt/Hr Coleta'], dayfirst=True, errors='coerce')

            # Aplica motor SLA
            df[['Prazo_Limite_SLA', 'Status_SLA']] = df.apply(classificar_sla, axis=1)

            # Separa os dados válidos
            df_valido = df[df['Status_SLA'].isin(['No Prazo', 'Atrasado'])]
        else:
            st.error("As colunas 'Dt/Hr Disp Coleta' e 'Dt/Hr Coleta' não foram encontradas no arquivo.")
            st.stop()

    st.success("Processamento concluído com sucesso!")
    
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Linhas Originais", f"{qtd_original}")
    col_b.metric("Linhas Pós-Filtros", f"{qtd_pos_limpeza}")
    col_c.metric("Linhas Descartadas", f"{qtd_original - qtd_pos_limpeza}")
    
    st.markdown("---")

    # ==============================================================================
    # 4. GERAÇÃO DO REPORT
    # ==============================================================================
    if not df_valido.empty:
        st.subheader("📊 REPORT GERENCIAL: Nível de Serviço (NS) de Coletas")
        
        resumo = df_valido.groupby('Transportadora').agg(
            Total_Pedidos=('Pedido', 'count'),
            Coletados_No_Prazo=('Status_SLA', lambda x: (x == 'No Prazo').sum()),
            Coletados_Atrasados=('Status_SLA', lambda x: (x == 'Atrasado').sum()),
            Media_Peso_Atrasados_KG=('Status_SLA', lambda x: df_valido.loc[x[x == 'Atrasado'].index, 'Peso'].mean())
        )

        try:
            resumo['Atrasos Mono (%)'] = df_valido.groupby('Transportadora').apply(lambda g: calc_perc_atraso_tipo(g, 'Mono'), include_groups=False).round(2)
            resumo['Atrasos Multi (%)'] = df_valido.groupby('Transportadora').apply(lambda g: calc_perc_atraso_tipo(g, 'Multi'), include_groups=False).round(2)
        except TypeError:
            resumo['Atrasos Mono (%)'] = df_valido.groupby('Transportadora').apply(lambda g: calc_perc_atraso_tipo(g, 'Mono')).round(2)
            resumo['Atrasos Multi (%)'] = df_valido.groupby('Transportadora').apply(lambda g: calc_perc_atraso_tipo(g, 'Multi')).round(2)

        resumo['NS de Coleta (%)'] = (resumo['Coletados_No_Prazo'] / resumo['Total_Pedidos'] * 100).round(2)
        resumo['Media_Peso_Atrasados_KG'] = resumo['Media_Peso_Atrasados_KG'].round(2).fillna(0)

        cols_ordem = ['Total_Pedidos', 'Coletados_No_Prazo', 'Coletados_Atrasados', 'Media_Peso_Atrasados_KG', 'Atrasos Mono (%)', 'Atrasos Multi (%)', 'NS de Coleta (%)']
        resumo_display = resumo[cols_ordem].sort_values('NS de Coleta (%)', ascending=True)

        st.dataframe(resumo_display, use_container_width=True)
        
        st.markdown("---")
        st.subheader("📥 Exportação de Dados")
        
        df_atrasados = df_valido[df_valido['Status_SLA'] == 'Atrasado'].copy()
        output_cols_atrasados = ['Transportadora', 'Pedido', 'Dt/Hr Pgto', 'Dt/Hr Disp Coleta', 'Dt/Hr Coleta', 'Prazo_Limite_SLA', 'Status_SLA', 'Status Tracking']
        
        cols_existentes = [c for c in output_cols_atrasados if c in df_atrasados.columns]
        df_atrasados_out = df_atrasados[cols_existentes]

        csv_atrasados = convert_df_to_csv(df_atrasados_out)
        csv_completo = convert_df_to_csv(df)

        col_down1, col_down2 = st.columns(2)
        
        with col_down1:
            st.download_button(
                label="📦 Baixar Pedidos Atrasados (CSV)",
                data=csv_atrasados,
                file_name='Pedidos_Coletados_Atrasados.csv',
                mime='text/csv',
            )
            
        with col_down2:
            st.download_button(
                label="📋 Baixar Base Completa Processada (CSV)",
                data=csv_completo,
                file_name='Base_Processada_SLA_Coleta_Limpa.csv',
                mime='text/csv',
            )
    else:
        st.warning("⚠️ Aviso: Nenhum pedido classificado como 'No Prazo' ou 'Atrasado' após os filtros.")