param ubicacion string = 'southcentralus'
param imagen string
param origenes string = '*'

@secure()
param claveServicios string = newGuid()

resource entorno 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'ceneval-entorno'
  location: ubicacion
  properties: {}
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ceneval-api'
  location: ubicacion
  properties: {
    managedEnvironmentId: entorno.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      secrets: [
        {
          name: 'clave-servicios'
          value: claveServicios
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: imagen
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: [
            {
              name: 'CLAVE_SERVICIOS'
              secretRef: 'clave-servicios'
            }
            {
              name: 'ORIGENES'
              value: origenes
            }
            {
              name: 'PROCESOS_SIMULACION'
              value: '2'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
}

output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
