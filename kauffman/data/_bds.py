import requests
import pandas as pd
import kauffman.constants as c
import os
from joblib import Parallel, delayed
import numpy as np


def _county_fips(df):
    return df \
        .assign(county=lambda x: x['state'] + x['county']) \
        .drop('state', 1)


def _fetch_data(url, session):
    success = False
    attempts = 0
    while not success and attempts < 5:
        try:
            r = session.get(url)
            if r.status_code == 200:
                df = pd.DataFrame(r.json()[1:], columns=r.json()[0])
                success = True
            elif r.status_code == 204:
                df = pd.DataFrame()
                success = True
            else:
                attempts += 1
                print(f'ERROR. Code: {r}. Attempt #{attempts}/5. URL: {url}')
                df = pd.DataFrame()
        except Exception as e:
            attempts += 1
            print(f'ERROR. Attempt #{attempts}/5. URL: {url}. Error: {e}')
            df = pd.DataFrame()
    if not success:
        print(
            f'\nRAN OUT OF ATTEMPTS for url: {url}', 
            '\n**If unexpected, please check your key and other parameters.**\n'
        )
    return df

def _build_url(variables, region, strata, key, state_fips=None, year='*'):
    flag_var = [f'{var}_F' for var in variables]
    var_string = ",".join(variables + strata + flag_var)
    
    region_string = {
        'us':'us:*',
        'state':f'state:{state_fips}',
        'msa':f'{c.api_msa_string}:*',
        'county':f'county:*&in=state:{state_fips}'
    }[region]

    naics_string = '&NAICS=00' if 'NAICS' not in strata else ''
    
    return f'https://api.census.gov/data/timeseries/bds?get={var_string}' \
        f'&for={region_string}&YEAR={year}{naics_string}&key={key}'


def _mark_flagged(df, variables):
    df[variables] = df[variables] \
        .apply(
            lambda x: df[f'{x.name}_F'] \
                .where(df[f'{x.name}_F'].isin(['D', 'S', 'X']), x) \
                .replace(['D', 'S', 'X'], np.NaN)
        )
    return df


def _bds_data_create(variables, region, strata, get_flags, key, n_threads):
    s = requests.Session()
    parallel = Parallel(n_jobs=n_threads, backend='threading')

    if 'NAICS' not in strata or region == 'us':
        df = _fetch_data(_build_url(variables, region, strata, key, '*'), s)
    else:
        with parallel:
            df = pd.concat(
                parallel(
                    delayed(_fetch_data)(
                        _build_url(variables, region, strata, key, '*', year),
                        s
                    )
                    for year in range(1978, 2020)
                )
            )
            
    s.close()

    if len(df) == 0: 
        raise Exception(
            'The data fetch returned an empty dataframe. Please double check' \
            'that you have a valid key.'
        )

    flags = [f'{var}_F' for var in variables] if get_flags else []

    return df \
        .pipe(lambda x: _county_fips(x) if region == 'county' else x) \
        .rename(columns={
            **{c.api_msa_string:'fips'},
            **{region: 'fips', 'YEAR': 'time', 'NAICS':'naics'}, 
            **{x:x.lower() for x in strata}
            }
        ) \
        .assign(
            fips=lambda x: '00' if region == 'us' else x['fips'],
            region=lambda x: x['fips'].map(c.all_fips_to_name),
            industry=lambda x: x['naics'].map(c.naics_code_to_abb(2))
        ) \
        .apply(
            lambda x: pd.to_numeric(x, errors='ignore') \
                if x.name in variables + ['time'] else x
        ) \
        .pipe(_mark_flagged, variables) \
        .sort_values(['fips', 'time'] + strata) \
        .reset_index(drop=True) \
        [
            ['fips', 'region', 'time'] \
            + [x.lower() for x in strata] \
            + variables + flags
        ]


def check_strata_valid(obs_level, strata):
    valid_crosses = c.bds_valid_crosses

    if not strata:
        valid = True
    elif obs_level in ['state', 'county', 'msa']:
        strata = set(strata + [obs_level.upper()])
        valid = strata in valid_crosses
    elif obs_level == 'all':
        valid = all(
            set(strata + [o.upper()]) in valid_crosses 
            for o in ['us', 'state', 'msa', 'county']
        )
    else:
        strata = set(strata)
        valid = strata in valid_crosses

    return valid


def bds(
    series_lst, obs_level='all', strata=[], get_flags=False, 
    key=os.getenv('CENSUS_KEY'), n_threads=1
):
    """ 
    Create a pandas data frame with results from a BDS query. 
    Column order: fips, region, time, series_lst.

    Keyword arguments:

    series_lst-- lst of variables to pull; 
        See https://www.census.gov/content/dam/Census/programs-surveys/business-dynamics-statistics/BDS_Codebook.pdf 
        or https://api.census.gov/data/timeseries/bds/variables.html
        
        # todo: NAICS is always used
        CBSA: Geography
        COUNTY: Geography
        DENOM: (DHS) denominator
        EMP: Number of employees
        ESTAB: Number of establishments
        ESTABS_ENTRY: Number of establishments born during the last 12 months
        ESTABS_ENTRY_RATE: Rate of establishments born during the last 12 months
        ESTABS_EXIT: Number of establishments exited during the last 12 months
        ESTABS_EXIT_RATE: Rate of establishments exited during the last 12 
            months
        FIRM: Number of firms
        FIRMDEATH_EMP: Number of employees associated with firm deaths during
            the last 12 months
        FIRMDEATH_ESTABS: Number of establishments associated with firm deaths
            during the last 12 months
        FIRMDEATH_FIRMS: Number of firms that exited during the last 12 months
        GEO_ID: Geographic identifier code
        JOB_CREATION: Number of jobs created from expanding and opening 
            establishments during the last 12 months
        JOB_CREATION_BIRTHS: Number of jobs created from opening establishments 
            during the last 12 months
        JOB_CREATION_CONTINUERS: Number of jobs created from expanding 
            establishments during the last 12 months
        JOB_CREATION_RATE: Rate of jobs created from expanding and opening 
            establishments during the last 12 months
        JOB_CREATION_RATE_BIRTHS: Rate of jobs created from opening 
            establishments during the last 12 months
        JOB_DESTRUCTION: Number of jobs lost from contracting and closing 
            establishments during the last 12 months
        JOB_DESTRUCTION_CONTINUERS: Number of jobs lost from contracting 
            establishments during the last 12 months
        JOB_DESTRUCTION_DEATHS: Number of jobs lost from closing establishments 
            during the last 12 months
        JOB_DESTRUCTION_RATE: Rate of jobs lost from contracting and closing 
            establishments during the last 12 months
        JOB_DESTRUCTION_RATE_DEATHS: Rate of jobs lost from closing 
            establishments during the last 12 months
        NATION: Geography
        NET_JOB_CREATION: Number of net jobs created from expanding/contracting 
            and opening/closing establishments during the last 12 months
        NET_JOB_CREATION_RATE: Rate of net jobs created from expanding/
            contracting and opening/closing establishments during the last 12 
            months
        REALLOCATION_RATE: Rate of reallocation during the last 12 months
        STATE: Geography
        SUMLEVEL: Summary Level code
        ucgid: Uniform Census Geography Identifier clause
        YEAR: Year

    strata--list of variables by which to stratify
        GEOCOMP: GEO_ID Component
        EAGE: Establishment age code
        EMPSZES: Employment size of establishments code
        EMPSZESI: Initial employment size of establishments code
        EMPSZFI: Employment size of firms code
        EMPSZFII: Initial employment size of firms code
        FAGE: Firm age code
        NAICS: 2017 NAICS Code
        METRO: Establishments located in Metropolitan or Micropolitan 
            Statistical Area indicator

        FAGE codes
            1   Total (0) All firm ages
            10  0 Years (1) Firms less than one year old
            20  1 Year (1) Firms one year old
            25  1-5 Years (2) Firms between one and five years old
            30  2 Years (1) Firms two years old
            40  3 Years (1) Firms three years old
            50  4 Years (1) Firms four years old
            60  5 Years (1) Firms five years old
            70  6-10 Years (0) Firms between six and ten years old
            75  11+ Years (2) Firms eleven or more years old
            80  11-15 Years (1) Firms between eleven and fifteen years old
            90  16-20 Years (1) Firms between sixteen and twenty years old
            100 21-25 Years (1) Firms b/w twenty one and twenty five years old
            110 26+ Years (1) Firms twenty six or more years old
            150 Left Censored (0) "Firms of unknown age (born before 1977)"

    obs_level--str or lst of the level of observation(s) to pull at.
        all:
        us:
        state:
        county:
        list of regions according to fips code

    first year available is 1978, last year is 2018
    """
    if type(obs_level) == list:
        region_lst = obs_level
    elif obs_level in ['us', 'state', 'county', 'msa']:
        region_lst = [obs_level]
    else:
        region_lst = ['us', 'state', 'county', 'msa']

    invalid_strata = set(strata) \
        - {'GEOCOMP', 'EAGE', 'EMPSZES', 'EMPSZESI', 'EMPSZFI', 'EMPSZFII', 
            'FAGE', 'NAICS', 'METRO'}
    if invalid_strata:
        raise Exception(
            f'Variables {invalid_strata} are invalid inputs to strata ' \
            'argument. Refer to the function documentation for valid strata.'
        )
    
    if len({'METRO', 'GEOCOMP'} - set(strata)) == 1:
        missing_var = {'METRO', 'GEOCOMP'} - set(strata)
        strata = strata + list(missing_var)
        print(
            'Warning: Variables METRO and GEOCOMP must be used together. ' \
            f'Variable {missing_var} has been added to strata list.')

    # Test that we have a valid strata crossing
    if not check_strata_valid(obs_level, strata):
        raise Exception(
            f'This is not a valid combination of strata for obs_level ' \
            f'{obs_level}. See ' \
            'https://www.census.gov/data/datasets/time-series/econ/bds/bds-datasets.html' \
            ' for a list of valid crossings.'
        )
    
    # Convert coded variables to their labeled versions
    strata = strata + [f'{var}_LABEL' for var in strata if var != 'GEOCOMP']

    return pd.concat(
            [
                _bds_data_create(
                    series_lst, region, strata, get_flags, key, n_threads
                )
                for region in region_lst
            ],
            axis=0
        )
