// Azure connectivity hub for the hybrid platform: a hub VNet reached from the on-premises sites over
// IKEv2 IPsec, logging to Log Analytics. Deployed per environment with main.bicepparam.
targetScope = 'resourceGroup'

@description('Azure region of the hub')
param location string = resourceGroup().location

@description('Address space of the hub VNet; must not overlap the sites')
param hubAddressSpace string = '10.70.0.0/16'

@description('On-premises sites: public IP of the site firewall and the site address ranges')
param sites array = [
  {
    name: 'hq'
    publicIp: '203.0.113.10'
    prefixes: ['10.10.0.0/16', '10.110.0.0/16']
  }
  {
    name: 'factory'
    publicIp: '203.0.113.20'
    prefixes: ['10.20.0.0/16']
  }
]

@secure()
@description('Pre-shared key for the site connections; comes from Key Vault in the pipeline')
param sharedKey string

@description('Days to keep logs')
@minValue(30)
param logRetentionDays int = 90

var tags = {
  platform: 'hybrid'
  managedBy: 'bicep'
  repo: 'hybrid-platform-runway'
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'law-hybrid-hub'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: logRetentionDays
  }
}

resource nsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: 'nsg-hub-workloads'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'allow-sites-in'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: '*'
          sourceAddressPrefixes: flatten(map(sites, s => s.prefixes))
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange: '*'
        }
      }
      {
        name: 'deny-internet-in'
        properties: {
          priority: 4000
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-hybrid-hub'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: [hubAddressSpace] }
    subnets: [
      {
        name: 'GatewaySubnet'
        properties: { addressPrefix: cidrSubnet(hubAddressSpace, 27, 0) }
      }
      {
        name: 'snet-workloads'
        properties: {
          addressPrefix: cidrSubnet(hubAddressSpace, 24, 1)
          networkSecurityGroup: { id: nsg.id }
        }
      }
    ]
  }
}

resource gwIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: 'pip-vpngw-hub'
  location: location
  tags: tags
  sku: { name: 'Standard', tier: 'Regional' }
  zones: ['1', '2', '3']
  properties: { publicIPAllocationMethod: 'Static' }
}

resource vpnGateway 'Microsoft.Network/virtualNetworkGateways@2024-05-01' = {
  name: 'vpngw-hub'
  location: location
  tags: tags
  properties: {
    gatewayType: 'Vpn'
    vpnType: 'RouteBased'
    vpnGatewayGeneration: 'Generation2'
    sku: { name: 'VpnGw2AZ', tier: 'VpnGw2AZ' }
    ipConfigurations: [
      {
        name: 'default'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          subnet: { id: '${vnet.id}/subnets/GatewaySubnet' }
          publicIPAddress: { id: gwIp.id }
        }
      }
    ]
  }
}

resource localGateways 'Microsoft.Network/localNetworkGateways@2024-05-01' = [for s in sites: {
  name: 'lng-${s.name}'
  location: location
  tags: tags
  properties: {
    gatewayIpAddress: s.publicIp
    localNetworkAddressSpace: { addressPrefixes: s.prefixes }
  }
}]

// IKEv2 only, the same suite as the AWS side: AES-256, SHA-256, DH group 20 (ECP384)
resource connections 'Microsoft.Network/connections@2024-05-01' = [for (s, i) in sites: {
  name: 'cn-${s.name}'
  location: location
  tags: tags
  properties: {
    connectionType: 'IPsec'
    connectionProtocol: 'IKEv2'
    virtualNetworkGateway1: { id: vpnGateway.id, properties: {} }
    localNetworkGateway2: { id: localGateways[i].id, properties: {} }
    sharedKey: sharedKey
    usePolicyBasedTrafficSelectors: false
    ipsecPolicies: [
      {
        ikeEncryption: 'AES256'
        ikeIntegrity: 'SHA256'
        dhGroup: 'ECP384'
        ipsecEncryption: 'GCMAES256'
        ipsecIntegrity: 'GCMAES256'
        pfsGroup: 'ECP384'
        saLifeTimeSeconds: 27000
        saDataSizeKilobytes: 102400000
      }
    ]
  }
}]

resource gwDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-log-analytics'
  scope: vpnGateway
  properties: {
    workspaceId: logs.id
    logs: [
      { categoryGroup: 'allLogs', enabled: true }
    ]
    metrics: [
      { category: 'AllMetrics', enabled: true }
    ]
  }
}

output vpnGatewayPublicIp string = gwIp.properties.ipAddress
output workloadSubnetId string = '${vnet.id}/subnets/snet-workloads'
